"""Discord bot DM provider with PRIVATE links and host-verified per-account destinations."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sys
import time
from typing import Any
from urllib.parse import quote, urlencode, urlsplit
from uuid import UUID

from sdk.discord_embeds import (
    DiscordRenderError, decode_reference, encode_reference, nonce, render_delivery, render_text,
)
from sdk.notification_stories import ContractError, delivery_operation, delivery_result, provider_capabilities
from sdk.notifications import destination_status, provider_context, register_provider
from sdk.plugin_protocol import GatewayRequestError, request

PLUGIN_ID = "official.discord-bot-notifications"
PROVIDER_ID = PLUGIN_ID + ".dm"
DISCORD_API = "https://discord.com/api/v10"
DISCORD_USER_AGENT = "UnnamedTrackingDiscordBot (https://github.com/Unbound-Timeline-Shelf/Unbound-Timeline-Shelf, 1.0)"
_USERNAME = re.compile(r"^[a-z0-9._]{2,32}$")
_SNOWFLAKE = re.compile(r"^[0-9]{17,20}$")
_LINK_TTL = 600


class PluginError(ValueError):
    """Safe user-facing plugin action failure."""


class DiscordForbiddenError(PluginError):
    """A definite HTTP 403 rejection; no message was accepted by Discord."""


class DiscordTemporaryError(PluginError):
    """Transient Discord failure; core owns retry timing and persisted attempts."""


class DiscordRateLimitError(DiscordTemporaryError):
    """HTTP 429: Discord did not process the request, so repeating it later is safe."""


class DiscordNotFoundError(PluginError):
    """HTTP 404: the channel or message no longer exists."""


def _actor(values: dict[str, Any], *, admin: bool = False) -> str:
    context = values.get("_plugin_context", {})
    if not isinstance(context, dict) or not context.get("user_id") or (admin and context.get("is_admin") is not True):
        raise PluginError("Administrator access is required." if admin else "Sign in to manage your Discord link.")
    try:
        return str(UUID(str(context["user_id"])))
    except (TypeError, ValueError, AttributeError):
        raise PluginError("Sign in to manage your Discord link.") from None


def _load(key: str, default: Any = None) -> Any:
    raw = request("storage.get", "plugin.storage", {"key": key}).get("value")
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        raise PluginError("Saved Discord configuration is damaged.") from None


def _store(key: str, value: Any) -> None:
    request("storage.put", "plugin.storage", {"key": key, "value": json.dumps(value)})


def _delete(key: str) -> None:
    request("storage.delete", "plugin.storage", {"key": key})


def _bot_config() -> dict[str, str]:
    config = _load("secrets/bot-config", {})
    token = config.get("token") if isinstance(config, dict) else None
    guild_id = config.get("guild_id") if isinstance(config, dict) else None
    if not isinstance(token, str) or not token or not isinstance(guild_id, str):
        raise PluginError("An administrator must configure the Discord bot token and server ID.")
    return {"token": token, "guild_id": guild_id}


def _discord(token: str, method: str, path: str, body: dict | None = None) -> Any:
    """Call Discord through the host's outbound gateway response contract."""
    payload: dict[str, Any] = {
        "url": DISCORD_API + path,
        "method": method,
        "headers": {
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": DISCORD_USER_AGENT,
        },
    }
    if body is not None:
        # network.outbound accepts an object under "body", not "json".
        payload["body"] = body
    response = request("network.request", "network.outbound", payload)
    if not isinstance(response, dict):
        raise PluginError("The Discord gateway returned an invalid response.")
    status = response.get("status")
    if not isinstance(status, int):
        raise PluginError("The Discord gateway did not return an HTTP status.")
    if status < 200 or status >= 300:
        if status == 401:
            raise PluginError("Discord rejected the bot token. Check that it is the current bot token.")
        if status == 403:
            raise DiscordForbiddenError("Discord denied access. Check the bot's server membership and permissions.")
        if status == 404:
            raise DiscordNotFoundError("Discord could not find the requested server or resource. Check the server ID and bot membership.")
        if status == 429:
            raise DiscordRateLimitError("Discord is rate limiting requests. Wait briefly and try again.")
        if status == 0:
            raise DiscordTemporaryError("Discord could not be reached. Check the host's outbound network and TLS configuration.")
        if status >= 500:
            raise DiscordTemporaryError("Discord is temporarily unavailable. Try again later.")
        raise PluginError(f"Discord returned HTTP {status} for this request.")
    if "data" not in response:
        raise PluginError("Discord returned a successful response without JSON data.")
    return response["data"]


def _member_by_username(token: str, guild_id: str, username: str) -> dict[str, Any] | None:
    username = username.casefold()
    after = "0"
    matches: list[dict[str, Any]] = []
    while True:
        response = _discord(token, "GET", f"/guilds/{quote(guild_id)}/members?limit=1000&after={after}")
        if not isinstance(response, list):
            raise PluginError("Discord did not return the server member list.")
        for member in response:
            user = member.get("user", {}) if isinstance(member, dict) else {}
            if str(user.get("username", "")).casefold() == username:
                matches.append(user)
                if len(matches) > 1:
                    raise PluginError("That Discord username matched more than one server member; use the unique Discord username.")
        if len(response) < 1000:
            return matches[0] if matches else None
        last = response[-1].get("user", {}).get("id")
        if not isinstance(last, str) or not _SNOWFLAKE.fullmatch(last):
            return None
        after = last


def _send_dm(token: str, discord_id: str, content: str) -> None:
    channel = _discord(token, "POST", "/users/@me/channels", {"recipient_id": discord_id})
    channel_id = channel.get("id") if isinstance(channel, dict) else None
    if not isinstance(channel_id, str):
        raise PluginError("Discord could not open a direct message channel.")
    _send_channel(token, channel_id, content)


def _send_channel(token: str, channel_id: str, content: str) -> None:
    title, description = "Tracking app", content
    if content.startswith("**") and "**\n" in content:
        title, description = content[2:].split("**\n", 1)
    # Keep bearer URLs in a short action, including links inside recovery instructions.
    lines = description.splitlines()
    link = None
    paragraphs = []
    for line in lines:
        candidate = line.strip()
        try:
            parsed = urlsplit(candidate)
            is_link = (parsed.scheme in {"http", "https"} and parsed.hostname
                       and not parsed.username and not any(char.isspace() for char in candidate))
        except ValueError:
            is_link = False
        if is_link:
            if link is None:
                link = candidate
                # Escape Markdown delimiters without changing the URL's decoded target.
                target = quote(link, safe=":/?#[]@!$&'*+,;=%")
                paragraphs.append(f"Click [here]({target}) to continue.")
            elif candidate != link:
                paragraphs.append(line)
        elif candidate:
            paragraphs.append(line)
    description = "\n\n".join(paragraphs)
    description = description.replace(". If you did not request", ".\n\nIf you did not request")
    description = re.sub(r"(?<=code is )([0-9]{8})(?![0-9])", r"**\1**", description)
    embed = {"title": title[:256], "description": description[:4096], "color": 3430612,
             "footer": {"text": "Your tracking app · Notification"}}
    if link:
        embed["url"] = link
    path = f"/channels/{channel_id}/messages"
    try:
        _discord(token, "POST", path, {"embeds": [embed], "allowed_mentions": {"parse": []}})
    except DiscordForbiddenError:
        # The gateway intentionally redacts remote error bodies. A 403 may be
        # missing Embed Links or broader access: try text once on the same target.
        # Suppress automatic URL embeds too; never retry an ambiguous acceptance.
        label = "View notification"
        if "reset" in title.casefold() and "password" in title.casefold():
            label = "Reset your password"
        elif "invit" in title.casefold():
            label = "Accept invitation"
        elif "verif" in title.casefold():
            label = "Verify destination"
        action = ""
        if link:
            target = quote(link, safe=":/?#[]@!$&'*+,;=%")
            description = description.replace(f"Click [here]({target}) to continue.", "")
            action = f"\n\n[{label}]({target})"
            if len(action) > 1700:
                action = "\n\nOpen your tracking app to use this notification's link."
        heading = f"**{title[:256]}**\n\n"
        text = heading + description[:2000 - len(heading) - len(action)].rstrip() + action
        _discord(token, "POST", path, {
            "content": text, "flags": 4, "allowed_mentions": {"parse": []},
        })


def _avatar_url(user: dict[str, Any] | None, *, size: int = 256) -> str | None:
    if not isinstance(user, dict) or not user.get("id") or not user.get("avatar"):
        return None
    return f"https://cdn.discordapp.com/avatars/{user['id']}/{user['avatar']}.png?size={size}"


_PERMISSION_NAMES = {
        1: "CREATE_INSTANT_INVITE", 2: "KICK_MEMBERS", 4: "BAN_MEMBERS", 8: "ADMINISTRATOR", 16: "MANAGE_CHANNELS", 32: "MANAGE_GUILD",
        1024: "VIEW_CHANNEL", 2048: "SEND_MESSAGES", 4096: "SEND_TTS_MESSAGES", 8192: "MANAGE_MESSAGES", 16384: "EMBED_LINKS", 32768: "ATTACH_FILES",
        65536: "READ_MESSAGE_HISTORY", 131072: "MENTION_EVERYONE", 262144: "USE_EXTERNAL_EMOJIS", 524288: "VIEW_GUILD_INSIGHTS", 1048576: "CONNECT",
        2097152: "SPEAK", 4194304: "MUTE_MEMBERS", 8388608: "DEAFEN_MEMBERS", 16777216: "MOVE_MEMBERS", 33554432: "USE_VAD",
        67108864: "PRIORITY_SPEAKER", 134217728: "STREAM", 268435456: "USE_APPLICATION_COMMANDS", 536870912: "MANAGE_THREADS", 1073741824: "USE_PUBLIC_THREADS",
        2147483648: "USE_PRIVATE_THREADS", 4294967296: "USE_EXTERNAL_STICKERS", 8589934592: "SEND_MESSAGES_IN_THREADS", 17179869184: "USE_EMBEDDED_ACTIVITIES",
        34359738368: "MODERATE_MEMBERS", 137438953472: "VIEW_AUDIT_LOG", 274877906944: "VIEW_GUILD_ANALYTICS", 1099511627776: "MANAGE_EVENTS",
        4398046511104: "VIEW_CREATOR_MONETIZATION_ANALYTICS", 8796093022208: "USE_SOUNDBOARD", 17592186044416: "CREATE_GUILD_EXPRESSIONS",
        35184372088832: "CREATE_EVENTS", 70368744177664: "USE_EXTERNAL_SOUNDS", 140737488355328: "SEND_VOICE_MESSAGES",
}


def _permission_names(permission_value: int) -> list[str]:
    return [name for bit, name in _PERMISSION_NAMES.items() if permission_value & bit]


def _bot_snapshot(token: str, guild_id: str) -> dict[str, Any]:
    started = time.monotonic()
    bot = _discord(token, "GET", "/users/@me")
    if not isinstance(bot, dict) or not bot.get("id"):
        raise PluginError("Discord did not return the configured bot identity.")
    bot_id = str(bot["id"])
    guild = _discord(token, "GET", f"/guilds/{quote(guild_id)}?with_counts=true")
    member = _discord(token, "GET", f"/guilds/{quote(guild_id)}/members/{quote(bot_id)}")
    roles = _discord(token, "GET", f"/guilds/{quote(guild_id)}/roles")
    elapsed_ms = round((time.monotonic() - started) * 1000)
    if not isinstance(guild, dict) or not guild.get("id"):
        raise PluginError("Discord could not read the configured server.")
    if not isinstance(member, dict):
        member = {}
    if not isinstance(roles, list):
        roles = []
    member_role_ids = [str(rid) for rid in member.get("roles", [])]
    if str(guild.get("id")) not in member_role_ids:
        member_role_ids.insert(0, str(guild.get("id")))
    role_by_id = {str(role.get("id")): role for role in roles if isinstance(role, dict)}
    role_names = [str(role_by_id[rid].get("name")) for rid in member_role_ids if rid in role_by_id]
    permission_value = 0
    for role_id in member_role_ids:
        role = role_by_id.get(role_id)
        if not isinstance(role, dict):
            continue
        try:
            permission_value |= int(role.get("permissions", "0"))
        except (TypeError, ValueError):
            continue
    return {
        "bot": {
            "id": bot_id, "username": str(bot.get("username", "")), "global_name": bot.get("global_name"), "discriminator": str(bot.get("discriminator", "0")),
            "avatar_url": _avatar_url(bot), "verified": bot.get("verified"), "bot": bot.get("bot") is True, "public_flags": bot.get("public_flags"),
            "invite_url": f"https://discord.com/oauth2/authorize?client_id={quote(bot_id)}&scope=bot%20applications.commands", "recommended_intents": ["GUILDS", "GUILD_MEMBERS"],
        },
        "guild": {
            "id": str(guild.get("id")), "name": str(guild.get("name", "")), "icon_url": f"https://cdn.discordapp.com/icons/{guild['id']}/{guild['icon']}.png?size=256" if guild.get("icon") else None,
            "description": guild.get("description"), "owner_id": guild.get("owner_id"), "member_count": guild.get("approximate_member_count"), "online_count": guild.get("approximate_presence_count"),
            "verification_level": guild.get("verification_level"), "premium_tier": guild.get("premium_tier"), "premium_subscription_count": guild.get("premium_subscription_count"),
            "premium_progress_bar_enabled": guild.get("premium_progress_bar_enabled"), "preferred_locale": guild.get("preferred_locale"), "features": guild.get("features", []), "nsfw_level": guild.get("nsfw_level"),
            "vanity_url_code": guild.get("vanity_url_code"), "afk_channel_id": guild.get("afk_channel_id"), "afk_timeout": guild.get("afk_timeout"), "system_channel_id": guild.get("system_channel_id"),
            "rules_channel_id": guild.get("rules_channel_id"), "public_updates_channel_id": guild.get("public_updates_channel_id"), "explicit_content_filter": guild.get("explicit_content_filter"),
            "default_message_notifications": guild.get("default_message_notifications"), "mfa_level": guild.get("mfa_level"), "widget_enabled": guild.get("widget_enabled"),
        },
        "bot_member": {"nickname": member.get("nick"), "joined_at": member.get("joined_at"), "pending": member.get("pending"), "role_names": role_names, "role_count": len(role_names), "permissions": permission_value, "permission_names": _permission_names(permission_value)},
        "health": {"api_ok": True, "request_ms": elapsed_ms},
    }


def _linked_accounts(value: Any) -> list[dict[str, Any]]:
    """Read both the original single-link format and the multi-account format."""
    if not isinstance(value, dict):
        return []
    accounts = value.get("accounts")
    if isinstance(accounts, list):
        return [dict(account) for account in accounts if isinstance(account, dict) and _SNOWFLAKE.fullmatch(str(account.get("discord_id", "")))]
    if _SNOWFLAKE.fullmatch(str(value.get("discord_id", ""))):
        return [dict(value)]
    return []


def _save_linked_accounts(user_id: str, accounts: list[dict[str, Any]]) -> None:
    """Persist a multi-account list while retaining legacy fields for old clients."""
    if not accounts:
        _delete("links/" + user_id)
        return
    _store("links/" + user_id, {**accounts[0], "accounts": accounts})


def get_destinations(values: dict[str, Any]) -> dict[str, Any]:
    """Display host proof, never the older optional profile-link verification."""
    actor = _actor(values)
    page = destination_status(after=values.get("after"), limit=100)
    installation = str(UUID(page["installation_id"]))
    destinations = []
    for status in page["destinations"]:
        item = dict(status)
        destination_id = str(UUID(item["id"]))
        if item["provider_id"] == ACCOUNT_PROVIDER_ID:
            key = f"account-dm/destinations/{installation}/{destination_id}"
        elif item["provider_id"] == CHANNEL_PROVIDER_ID:
            key = f"channel/destinations/{installation}/{destination_id}"
        else:
            key = None
        record = _load(key, {}) if key else {}
        # Local identity labels are plugin-owned; a stale mapping must not be
        # attached to host proof for another revision or actor.
        if (isinstance(record, dict) and not record.get("retired")
                and record.get("user_id") == actor and record.get("revision") == item["revision"]):
            item.update({key: record[key] for key in ("username", "discord_id", "channel_id") if key in record})
        destinations.append(item)
    return {"destinations": destinations, "next_after": page.get("next_after")}


def list_servers(values: dict[str, Any]) -> dict[str, Any]:
    """Administrator-only, bounded bot membership discovery; never echo credentials."""
    _actor(values, admin=True)
    token = values.get("token")
    if token is None or token == "":
        token = _bot_config()["token"]
    if not isinstance(token, str) or not token.strip() or len(token) > 512:
        raise PluginError("Enter a valid bot token or configure it first.")
    after = values.get("after", "0")
    if after != "0" and (not isinstance(after, str) or not _SNOWFLAKE.fullmatch(after)):
        raise PluginError("The server-list cursor is invalid.")
    response = _discord(token.strip(), "GET", f"/users/@me/guilds?limit=100&after={after}")
    if not isinstance(response, list):
        raise PluginError("Discord did not return the bot server list.")
    servers = [{"id": item["id"], "name": str(item.get("name", item["id"]))[:100]}
               for item in response if isinstance(item, dict) and _SNOWFLAKE.fullmatch(str(item.get("id", "")))]
    return {"servers": servers, "next_after": servers[-1]["id"] if len(response) == 100 and servers else None}


def get_saved_config(values: dict[str, Any]) -> dict[str, Any]:
    """Read owned configuration without waiting for Discord's remote directory."""
    return _get_config(values, refresh_remote=False)


def get_config(values: dict[str, Any]) -> dict[str, Any]:
    """Explicit refresh retains the existing live Discord identity/health behavior."""
    return _get_config(values, refresh_remote=True)


def _get_config(values: dict[str, Any], *, refresh_remote: bool) -> dict[str, Any]:
    user_id = _actor(values)
    config = _load("secrets/bot-config", {})
    accounts = _linked_accounts(_load("links/" + user_id, {}))
    result: dict[str, Any] = {"configured": isinstance(config, dict) and bool(config.get("token") and config.get("guild_id")), "bot_configured": isinstance(config, dict) and bool(config.get("token") and config.get("guild_id")), "guild_id": str(config.get("guild_id", "")) if isinstance(config, dict) else "", "linked": bool(accounts), "accounts": []}
    if result["configured"] and refresh_remote:
        try:
            result.update(_bot_snapshot(str(config["token"]), str(config["guild_id"])))
        except GatewayRequestError:
            result["health"] = {"api_ok": False}; result["bot_error"] = "Discord could not be reached right now."
        except PluginError as exc:
            result["health"] = {"api_ok": False}; result["bot_error"] = str(exc)
    if result["configured"] and refresh_remote:
        for account in accounts:
            item = dict(account)
            linked_id = str(account["discord_id"])
            try:
                linked_user = _discord(str(config["token"]), "GET", f"/users/{quote(linked_id)}")
                linked_member = _discord(str(config["token"]), "GET", f"/guilds/{quote(str(config['guild_id']))}/members/{quote(linked_id)}")
                if isinstance(linked_user, dict):
                    item.update({"username": linked_user.get("username", ""), "global_name": linked_user.get("global_name"), "avatar_url": _avatar_url(linked_user)})
                if isinstance(linked_member, dict):
                    item.update({"server_nickname": linked_member.get("nick"), "server_joined_at": linked_member.get("joined_at"), "server_roles": linked_member.get("roles", [])})
            except (GatewayRequestError, PluginError):
                result["link_warning"] = "One or more linked Discord accounts could not be refreshed."
            result["accounts"].append(item)
    else:
        result["accounts"] = accounts
    if accounts:
        result.update({key: value for key, value in accounts[0].items() if key != "accounts"})
        result["discord_id"] = str(accounts[0]["discord_id"])
        if result["accounts"]:
            result.update({key: result["accounts"][0].get(key) for key in ("username", "global_name", "avatar_url", "server_nickname", "server_joined_at", "server_roles")})
    return result


def save_bot_config(values: dict[str, Any]) -> dict[str, Any]:
    _actor(values, admin=True)
    token = str(values.get("token", "")).strip(); guild_id = str(values.get("guild_id", "")).strip()
    if not token or not _SNOWFLAKE.fullmatch(guild_id):
        raise PluginError("Enter a valid Discord bot token and server ID.")
    try:
        snapshot = _bot_snapshot(token, guild_id)
    except PluginError as exc:
        if str(exc) != "Discord did not return the configured bot identity.":
            raise
        # A successful but incomplete /users/@me response is not proof of a
        # bad token. Save it so the admin can inspect/retry configuration.
        _store("secrets/bot-config", {"token": token, "guild_id": guild_id})
        return {
            "ok": True,
            "warning": str(exc) + " The configuration was saved; retry validation after checking Discord's response.",
        }
    _store("secrets/bot-config", {"token": token, "guild_id": guild_id})
    return {"ok": True, "message": f"Connected as {snapshot['bot']['username']} to {snapshot['guild']['name']}."}


def clear_bot_token(values: dict[str, Any]) -> dict[str, Any]:
    _actor(values, admin=True); _delete("secrets/bot-config")
    return {"ok": True, "message": "Bot token and server configuration removed. User links were retained."}


def link_private(values: dict[str, Any]) -> dict[str, Any]:
    """Link an intended recipient without claiming proof or SECURE eligibility."""
    user_id = _actor(values)
    config = _bot_config()
    username = str(values.get("username", "")).strip()
    if not _USERNAME.fullmatch(username):
        raise PluginError("Enter your exact Discord username.")
    member = _member_by_username(config["token"], config["guild_id"], username)
    if member is None or not _SNOWFLAKE.fullmatch(str(member.get("id", ""))):
        raise PluginError("That Discord username was not found in the configured server.")
    accounts = _linked_accounts(_load("links/" + user_id, {}))
    discord_id = str(member["id"])
    if any(str(account.get("discord_id")) == discord_id for account in accounts):
        raise PluginError("That Discord account is already linked.")
    accounts.append({"discord_id": discord_id, "linked_at": int(time.time())})
    _save_linked_accounts(user_id, accounts)
    return {"ok": True, "message": "Discord account linked for PRIVATE notifications. For SECURE recovery, add and verify a Discord account DM in your notification settings."}


def start_link(values: dict[str, Any]) -> dict[str, Any]:
    user_id = _actor(values); config = _bot_config(); username = str(values.get("username", "")).strip()
    if not _USERNAME.fullmatch(username):
        raise PluginError("Enter your Discord username exactly as shown by Discord.")
    member = _member_by_username(config["token"], config["guild_id"], username)
    if member is None or not _SNOWFLAKE.fullmatch(str(member.get("id", ""))):
        raise PluginError("That Discord username was not found in the configured server.")
    code = f"{secrets.randbelow(100_000_000):08d}"
    _store("pending-links/" + user_id, {"discord_id": str(member["id"]), "code_hash": hashlib.sha256(code.encode()).hexdigest(), "expires_at": int(time.time()) + _LINK_TTL, "attempts": 0})
    _send_dm(config["token"], str(member["id"]), f"Your verification code is **{code}**.")
    return {"ok": True, "message": "Verification code sent to your Discord DMs.", "expires_in_seconds": _LINK_TTL}


def confirm_link(values: dict[str, Any]) -> dict[str, Any]:
    user_id = _actor(values); pending = _load("pending-links/" + user_id)
    if not isinstance(pending, dict) or int(pending.get("expires_at", 0)) < int(time.time()):
        raise PluginError("Your verification code has expired. Start the link again.")
    attempts = int(pending.get("attempts", 0))
    if attempts >= 5:
        raise PluginError("Too many verification attempts. Start the link again.")
    code = str(values.get("code", "")); pending["attempts"] = attempts + 1; _store("pending-links/" + user_id, pending)
    if not hmac.compare_digest(hashlib.sha256(code.encode()).hexdigest(), str(pending.get("code_hash", ""))):
        raise PluginError("That verification code is incorrect.")
    accounts = _linked_accounts(_load("links/" + user_id, {}))
    discord_id = str(pending["discord_id"])
    if any(str(account.get("discord_id")) == discord_id for account in accounts):
        _delete("pending-links/" + user_id)
        raise PluginError("That Discord account is already linked.")
    accounts.append({"discord_id": discord_id, "linked_at": int(time.time())})
    _save_linked_accounts(user_id, accounts)
    _delete("pending-links/" + user_id)
    return {"ok": True, "message": "Discord account linked. Notifications will be sent to all linked Discord accounts."}


def unlink(values: dict[str, Any]) -> dict[str, Any]:
    user_id = _actor(values)
    discord_id = str(values.get("discord_id", "")).strip()
    accounts = _linked_accounts(_load("links/" + user_id, {}))
    if discord_id:
        accounts = [account for account in accounts if str(account.get("discord_id")) != discord_id]
    else:
        accounts = []
    _save_linked_accounts(user_id, accounts)
    _delete("pending-links/" + user_id)
    return {"ok": True, "message": "Discord account unlinked." if discord_id else "All Discord accounts unlinked."}


def configure_destination(values: dict[str, Any]) -> dict[str, Any]:
    """Allow PRIVATE host routing after this user has linked an intended Discord recipient."""
    user_id = _actor(values)
    accounts = _linked_accounts(_load("links/" + user_id))
    if not accounts:
        raise PluginError("Link at least one Discord account before enabling this PRIVATE destination.")
    return {"ok": True, "message": "Linked Discord account is ready for PRIVATE notifications."}


def retire_destination(values: dict[str, Any]) -> dict[str, Any]:
    """Remove the user's routing identity when they retire this destination."""
    user_id = _actor(values)
    _delete("links/" + user_id)
    _delete("pending-links/" + user_id)
    return {"ok": True, "message": "Discord notification destination retired and account unlinked."}


def test_dm(values: dict[str, Any]) -> dict[str, Any]:
    user_id = _actor(values); config = _bot_config()
    discord_id = str(values.get("discord_id", "")).strip()
    accounts = _linked_accounts(_load("links/" + user_id))
    account = next((item for item in accounts if str(item.get("discord_id")) == discord_id), None) if discord_id else (accounts[0] if accounts else None)
    if account is None:
        raise PluginError("Select a linked Discord account first.")
    _send_dm(config["token"], str(account["discord_id"]), "Discord notification test from your tracking app.")
    account["last_test_at"] = int(time.time())
    _save_linked_accounts(user_id, accounts)
    return {"ok": True, "message": "Test DM sent."}


def deliver(values: dict[str, Any]) -> dict[str, Any]:
    """Send normal PRIVATE notifications to recipients mapped to the host-supplied user context."""
    try:
        user_id = _actor(values); delivery = values.get("delivery")
        if not isinstance(delivery, dict):
            return {"success": False, "retryable": False, "error": "delivery_invalid"}
        context = values.get("_notification_context")
        destination = context.get("destination") if isinstance(context, dict) else None
        if (
            not isinstance(context, dict)
            or context.get("operation") != "deliver"
            or not isinstance(destination, dict)
            or destination.get("kind") != "discord_bot_dm"
        ):
            return {"success": False, "retryable": False, "error": "notification_context_invalid"}
        title = str(delivery.get("title", "Notification"))[:250]; body = str(delivery.get("body", ""))[:1500]; content = f"**{title}**\n{body}".strip()[:1900]
        config = _bot_config(); accounts = _linked_accounts(_load("links/" + user_id))
        if not accounts:
            return {"success": False, "retryable": False, "error": "recipient_not_linked"}
        delivered_at = int(time.time())
        for account in accounts:
            _send_dm(config["token"], str(account["discord_id"]), content or "Notification")
            account["last_delivery_at"] = delivered_at
        _save_linked_accounts(user_id, accounts)
    except GatewayRequestError as exc:
        retryable = exc.code in {"unavailable", "rate_limited"}
        return {"success": False, "retryable": retryable, "error": "discord_gateway_unavailable" if retryable else "discord_permission_denied"}
    except DiscordTemporaryError:
        return {"success": False, "retryable": True, "error": "discord_temporarily_unavailable"}
    except PluginError:
        return {"success": False, "retryable": False, "error": "discord_delivery_failed"}
    return {"success": True, "retryable": False}



# Presentation declared for the per-account DM and server-channel providers. Bot messages can be
# edited and replied to, carry link buttons and up to ten embeds; the package keeps every message
# inside those hard limits (sdk.discord_embeds).
BOT_CAPABILITIES = provider_capabilities(
    max_batch_items=8, message_updates="edit", threaded_follow_ups=True, rich_embeds=True,
    images={"max_images": 4, "external_urls": True}, action_buttons=5, links=True,
    live_page_links=True, max_title_chars=256, max_text_chars=4096, max_payload_bytes=30000,
)


def _post_rich(token: str, channel_id: str, delivery: dict[str, Any], operation: str, reference: str | None) -> dict[str, Any]:
    """Create the message for a send or follow-up and return its opaque `channel:message` reference."""
    body = render_delivery(delivery, components=True)
    if not body["components"]:
        del body["components"]
    unique = nonce(delivery.get("idempotency_key"))
    if unique:
        # A repeat after a crash with the same key is answered with the original message.
        body["nonce"] = unique
        body["enforce_nonce"] = True
    if operation == "follow_up" and reference:
        try:
            earlier_channel, earlier = decode_reference(reference)
        except DiscordRenderError:
            earlier_channel = earlier = ""
        if earlier_channel == channel_id:
            body["message_reference"] = {"message_id": earlier, "channel_id": channel_id, "fail_if_not_exists": False}
    path = f"/channels/{channel_id}/messages"
    try:
        data = _discord(token, "POST", path, body)
    except DiscordForbiddenError:
        # Missing Embed Links is indistinguishable from other 403s; one plain attempt, links suppressed.
        data = _discord(token, "POST", path, {"content": render_text(delivery), "flags": 4, "allowed_mentions": {"parse": []}})
    created = data.get("id") if isinstance(data, dict) else None
    try:
        return delivery_result(success=True, remote_ref=encode_reference(channel_id, created))
    except DiscordRenderError:
        return delivery_result(success=True)


def _edit_rich(token: str, channel_id: str, delivery: dict[str, Any], reference: str) -> dict[str, Any]:
    """Replace the earlier message; a deleted, foreign or uneditable one is reported as gone."""
    try:
        earlier_channel, earlier = decode_reference(reference)
    except DiscordRenderError:
        return delivery_result(success=False, gone=True)
    if earlier_channel != channel_id:
        # A reference only ever applies to the destination that produced it.
        return delivery_result(success=False, gone=True)
    body = render_delivery(delivery, components=True)
    body["content"] = None
    try:
        _discord(token, "PATCH", f"/channels/{channel_id}/messages/{earlier}", body)
    except (DiscordNotFoundError, DiscordForbiddenError):
        return delivery_result(success=False, gone=True)
    return delivery_result(success=True, remote_ref=reference)


def _deliver_rich(token: str, channel_id: str, delivery: dict[str, Any]) -> dict[str, Any]:
    operation, reference = delivery_operation(delivery)
    if operation == "edit" and reference is not None:
        return _edit_rich(token, channel_id, delivery, reference)
    return _post_rich(token, channel_id, delivery, operation, reference)


def _dm_channel_id(token: str, discord_id: str) -> str:
    channel = _discord(token, "POST", "/users/@me/channels", {"recipient_id": discord_id})
    channel_id = channel.get("id") if isinstance(channel, dict) else None
    if not isinstance(channel_id, str) or not _SNOWFLAKE.fullmatch(channel_id):
        raise PluginError("Discord could not open a direct message channel.")
    return channel_id


# Separate from the grouped PRIVATE compatibility provider and its native configuration.
ACCOUNT_PROVIDER_ID = PLUGIN_ID + ".account-dm"
ACCOUNT_DEFINITION = {
    "destinations": [{
        "kind": "discord_account_dm", "label": "Discord account DM", "privacy": "PRIVATE",
        "verification_supported": True, "sensitive_supported": True, "recovery_supported": True,
        "fields": [{"id": "username", "label": "Discord username", "type": "text", "required": True,
                    "description": "Exact username in the configured Discord server. PRIVATE delivery works before verification.",
                    "validation": {"min_length": 2, "max_length": 32}}],
    }],
    "server_fields": [
        {"id": "token", "label": "Bot token", "type": "password", "required": True, "secret": True,
         "description": "Stored by this plugin, independently of its legacy native settings.", "validation": {"max_length": 512}},
        {"id": "guild_id", "label": "Discord server ID", "type": "text", "required": True,
         "validation": {"min_length": 17, "max_length": 20}},
    ],
    "configure_action": "configure-account-destination", "retire_action": "retire-account-destination",
    "test_action": "deliver-account", "features": {"multiple_destinations": True, "critical_supported": False},
    "capabilities": BOT_CAPABILITIES, "edit_action": "edit-account",
}


def _account_context(values: dict[str, Any], operation: str) -> dict[str, Any]:
    try:
        context = provider_context(values, operation=operation, provider_id=ACCOUNT_PROVIDER_ID)
        if context["scope"] == "destination" and context["destination"]["kind"] != "discord_account_dm":
            raise ValueError("Wrong destination kind")
        return context
    except (KeyError, TypeError, ValueError) as exc:
        raise PluginError("A core-authorized per-account Discord destination is required.") from exc


def _account_server_key(context: dict[str, Any]) -> str:
    return "account-dm/server/" + context["installation_id"]


def _account_key(context: dict[str, Any]) -> str:
    return f"account-dm/destinations/{context['installation_id']}/{context['destination']['id']}"


def _account_record(key: str) -> dict[str, Any] | None:
    record = _load(key)
    if record is not None and (not isinstance(record, dict) or type(record.get("revision")) is not int):
        raise PluginError("Saved per-account configuration is damaged; configure it again.")
    return record


def _current_account_server(context: dict[str, Any]) -> dict[str, Any]:
    server = _account_record(_account_server_key(context))
    if not server or server.get("retired") or not server.get("token") or not server.get("guild_id"):
        raise PluginError("Configure this provider in administrator notification settings first.")
    return server


def configure_account_destination(values: dict[str, Any]) -> dict[str, Any]:
    """Only core revision-bound configuration can set a concrete Discord target."""
    context = _account_context(values, "configure")
    actor = _actor(values, admin=context["scope"] == "server")
    configuration = values.get("configuration")
    if not isinstance(configuration, dict):
        raise PluginError("Discord configuration fields are required.")
    if context["scope"] == "server":
        if set(configuration) - {"token", "guild_id"}:
            raise PluginError("Unsupported Discord server configuration fields.")
        key = _account_server_key(context)
        current = _account_record(key)
        revision = context["revision"]
        if current and current["revision"] >= revision:
            raise PluginError("This server configuration is stale.")
        token = configuration.get("token", current.get("token") if current else None)
        guild_id = configuration.get("guild_id", current.get("guild_id") if current else None)
        if not isinstance(token, str) or not token.strip() or not isinstance(guild_id, str) or not _SNOWFLAKE.fullmatch(guild_id):
            raise PluginError("Enter a bot token and valid Discord server ID.")
        # Validate before storing; failed saves leave host routes inactive.
        _bot_snapshot(token.strip(), guild_id)
        _store(key, {"revision": revision, "token": token.strip(), "guild_id": guild_id})
        return {"configured": True}
    if set(configuration) - {"username"}:
        raise PluginError("Unsupported Discord account configuration fields.")
    key = _account_key(context)
    current = _account_record(key)
    revision = context["destination"]["revision"]
    if current and (current["revision"] >= revision or current.get("retired")):
        raise PluginError("This destination configuration is stale or retired.")
    server = _current_account_server(context)
    username = configuration.get("username", current.get("username") if current else None)
    if not isinstance(username, str) or not _USERNAME.fullmatch(username):
        raise PluginError("Enter your exact Discord username.")
    member = _member_by_username(server["token"], server["guild_id"], username)
    if member is None or not _SNOWFLAKE.fullmatch(str(member.get("id", ""))):
        raise PluginError("That username was not found in the configured Discord server.")
    # No code, DM or plugin assertion promotes host trust. Enrollment stays PRIVATE.
    _store(key, {"revision": revision, "server_revision": server["revision"], "user_id": actor,
                 "username": username, "discord_id": str(member["id"])})
    return {"configured": True}


def retire_account_destination(values: dict[str, Any]) -> dict[str, Any]:
    context = _account_context(values, "retire")
    actor = _actor(values)
    current = _account_record(_account_key(context))
    revision = context["destination"]["revision"]
    if current and (current["revision"] > revision or current.get("user_id", actor) != actor):
        raise PluginError("This retirement is stale or belongs to another user.")
    # Opaque tombstone; cannot restore target or reuse an old revision after deletion.
    _store(_account_key(context), {"revision": revision, "retired": True})
    return {"retired": True}


def deliver_account(values: dict[str, Any]) -> dict[str, Any]:
    """Deliver to exactly one revision-bound account; never fall back to broadcast."""
    try:
        context = _account_context(values, "deliver")
        actor = _actor(values)
        record = _account_record(_account_key(context))
        server = _current_account_server(context)
        if (not record or record.get("retired") or record["revision"] != context["destination"]["revision"]
                or record.get("user_id") != actor or record.get("server_revision") != server["revision"]
                or context["server_revision"] != server["revision"]
                or not _SNOWFLAKE.fullmatch(str(record.get("discord_id", "")))):
            raise PluginError("This configured account revision is unavailable.")
        delivery = values.get("delivery")
        if not isinstance(delivery, dict) or not isinstance(delivery.get("title"), str) or not isinstance(delivery.get("body"), str):
            raise PluginError("Notification content is invalid.")
        if "contract_version" in delivery:
            return _deliver_rich(server["token"], _dm_channel_id(server["token"], record["discord_id"]), delivery)
        content = f"**{delivery['title'][:250]}**\n{delivery['body']}"
        link = delivery.get("link")
        if isinstance(link, str) and link.startswith(("https://", "http://")):
            content += "\n" + link
        if len(content) > 1900:
            raise PluginError("This notification exceeds Discord message limits.")
        _send_dm(server["token"], record["discord_id"], content)
    except GatewayRequestError as exc:
        return {"success": False, "retryable": exc.code in {"unavailable", "rate_limited"}, "error": "discord_gateway_failed"}
    except DiscordTemporaryError:
        return {"success": False, "retryable": True, "error": "discord_temporarily_unavailable"}
    except (PluginError, KeyError, TypeError, ValueError):
        return {"success": False, "retryable": False, "error": "discord_account_unavailable"}
    return {"success": True, "retryable": False}



def edit_account(values: dict[str, Any]) -> dict[str, Any]:
    """Apply a story revision to the message this account destination sent earlier."""
    return deliver_account(values)


# Server channels are PUBLIC even when Discord restricts membership.
CHANNEL_PROVIDER_ID = PLUGIN_ID + ".channel"
CHANNEL_DEFINITION = {
    "destinations": [{"kind": "discord_bot_channel", "label": "Discord server channel", "privacy": "PUBLIC",
        "fields": [{"id": "channel_id", "label": "Discord channel ID", "type": "text",
            "description": "Choose an allowed default channel in Discord account settings, or enter its ID here. Channels receive PUBLIC announcements only.",
            "validation": {"max_length": 20}}]}],
    "server_fields": ACCOUNT_DEFINITION["server_fields"],
    "configure_action": "configure-channel-destination", "retire_action": "retire-channel-destination",
    "test_action": "deliver-channel", "features": {"multiple_destinations": True, "critical_supported": False},
    "capabilities": BOT_CAPABILITIES, "edit_action": "edit-channel",
}


def _channel_context(values: dict[str, Any], operation: str) -> dict[str, Any]:
    try:
        context = provider_context(values, operation=operation, provider_id=CHANNEL_PROVIDER_ID)
        if context["scope"] == "destination" and context["destination"]["kind"] != "discord_bot_channel":
            raise ValueError("Wrong destination kind")
        return context
    except (KeyError, TypeError, ValueError) as exc:
        raise PluginError("A core-authorized Discord channel destination is required.") from exc


def _channel_server_key(context: dict[str, Any]) -> str:
    return "channel/server/" + context["installation_id"]


def _channel_key(context: dict[str, Any]) -> str:
    return f"channel/destinations/{context['installation_id']}/{context['destination']['id']}"


def _channel_server(context: dict[str, Any]) -> dict[str, Any]:
    server = _account_record(_channel_server_key(context))
    if not server or server.get("retired") or not server.get("token") or not server.get("guild_id"):
        raise PluginError("Configure the channel provider in administrator notification settings first.")
    return server


def _allowed_channels(guild_id: str) -> list[dict[str, str]]:
    records = _load("channel-policy/" + guild_id, [])
    if not isinstance(records, list):
        raise PluginError("The channel allowlist is damaged; ask an administrator to save it again.")
    return [item for item in records if isinstance(item, dict) and _SNOWFLAKE.fullmatch(str(item.get("id", "")))]


def _check_channel(token: str, guild_id: str, channel_id: str) -> dict[str, Any]:
    if not isinstance(channel_id, str) or not _SNOWFLAKE.fullmatch(channel_id):
        raise PluginError("Enter a valid Discord channel ID.")
    if channel_id not in {item["id"] for item in _allowed_channels(guild_id)}:
        raise PluginError("An administrator must allow this channel first.")
    channel = _discord(token, "GET", "/channels/" + channel_id)
    if (not isinstance(channel, dict) or channel.get("id") != channel_id
            or channel.get("guild_id") != guild_id or channel.get("type") not in (0, 5)):
        raise PluginError("Choose a text or announcement channel in the configured server.")
    return channel


def list_directory(values: dict[str, Any]) -> dict[str, Any]:
    """Administrator-only Discord directory; never expose the bot token or host accounts."""
    _actor(values, admin=True)
    config = _bot_config()
    after = values.get("after", "0")
    if after != "0" and (not isinstance(after, str) or not _SNOWFLAKE.fullmatch(after)):
        raise PluginError("The member-list cursor is invalid.")
    channels = _discord(config["token"], "GET", f"/guilds/{config['guild_id']}/channels")
    members = _discord(config["token"], "GET", f"/guilds/{config['guild_id']}/members?limit=1000&after={after}")
    if not isinstance(channels, list) or not isinstance(members, list):
        raise PluginError("Discord did not return the server directory.")
    users = []
    for member in members:
        user = member.get("user", {}) if isinstance(member, dict) else {}
        if _SNOWFLAKE.fullmatch(str(user.get("id", ""))) and isinstance(user.get("username"), str):
            users.append({"id": user["id"], "username": user["username"], "label": member.get("nick") or user.get("global_name") or user["username"]})
    return {"channels": [{"id": item["id"], "name": str(item.get("name", item["id"]))[:100]} for item in channels
                if isinstance(item, dict) and item.get("type") in (0, 5) and _SNOWFLAKE.fullmatch(str(item.get("id", "")))],
            "users": users, "next_after": users[-1]["id"] if len(members) == 1000 and users else None,
            "allowed_channel_ids": [item["id"] for item in _allowed_channels(config["guild_id"])]}


def allow_channels(values: dict[str, Any]) -> dict[str, Any]:
    _actor(values, admin=True)
    config = _bot_config()
    ids = values.get("channel_ids")
    if (not isinstance(ids, list) or len(ids) > 500 or len(set(str(item) for item in ids)) != len(ids)
            or any(not isinstance(item, str) or not _SNOWFLAKE.fullmatch(item) for item in ids)):
        raise PluginError("Choose valid unique channel IDs.")
    channels = _discord(config["token"], "GET", f"/guilds/{config['guild_id']}/channels")
    if not isinstance(channels, list):
        raise PluginError("Discord did not return the server channel list.")
    found = {item["id"]: item for item in channels if isinstance(item, dict) and item.get("type") in (0, 5)
             and isinstance(item.get("id"), str)}
    if any(channel_id not in found for channel_id in ids):
        raise PluginError("Choose text or announcement channels from the configured server.")
    _store("channel-policy/" + config["guild_id"], [{"id": channel_id, "name": str(found[channel_id].get("name", channel_id))[:100]} for channel_id in ids])
    return {"message": "Allowed channels saved. Removed channels stop receiving deliveries immediately."}


def channel_choices(values: dict[str, Any]) -> dict[str, Any]:
    actor = _actor(values)
    config = _bot_config()
    return {"channels": _allowed_channels(config["guild_id"]), "selected": _load("channel-selection/" + actor, {}).get(config["guild_id"], "")}


def select_channel(values: dict[str, Any]) -> dict[str, Any]:
    actor = _actor(values)
    config = _bot_config()
    channel_id = values.get("channel_id")
    _check_channel(config["token"], config["guild_id"], channel_id)
    selections = _load("channel-selection/" + actor, {})
    selections[config["guild_id"]] = channel_id
    _store("channel-selection/" + actor, selections)
    return {"message": "Default channel selected. Add a Discord server channel destination in Notifications, then choose its notification types. Existing destinations keep their own target."}


def configure_channel_destination(values: dict[str, Any]) -> dict[str, Any]:
    context = _channel_context(values, "configure")
    actor = _actor(values, admin=context["scope"] == "server")
    configuration = values.get("configuration")
    if not isinstance(configuration, dict):
        raise PluginError("Discord configuration fields are required.")
    if context["scope"] == "server":
        if set(configuration) - {"token", "guild_id"}:
            raise PluginError("Unsupported Discord server configuration fields.")
        current = _account_record(_channel_server_key(context))
        if current and current["revision"] >= context["revision"]:
            raise PluginError("This server configuration is stale.")
        token = configuration.get("token", current.get("token") if current else None)
        guild_id = configuration.get("guild_id", current.get("guild_id") if current else None)
        if not isinstance(token, str) or not token.strip() or not isinstance(guild_id, str) or not _SNOWFLAKE.fullmatch(guild_id):
            raise PluginError("Enter a bot token and valid Discord server ID.")
        _bot_snapshot(token.strip(), guild_id)
        _store(_channel_server_key(context), {"revision": context["revision"], "token": token.strip(), "guild_id": guild_id})
        return {"configured": True}
    if set(configuration) - {"channel_id"}:
        raise PluginError("Unsupported Discord channel configuration fields.")
    server = _channel_server(context)
    current = _account_record(_channel_key(context))
    revision = context["destination"]["revision"]
    if current and (current["revision"] >= revision or current.get("retired") or current.get("user_id") != actor):
        raise PluginError("This channel configuration is stale or retired.")
    channel_id = configuration.get("channel_id") or (current.get("channel_id") if current else None)
    if not channel_id:
        channel_id = _load("channel-selection/" + actor, {}).get(server["guild_id"])
    _check_channel(server["token"], server["guild_id"], channel_id)
    _store(_channel_key(context), {"revision": revision, "server_revision": server["revision"], "user_id": actor, "channel_id": channel_id})
    return {"configured": True}


def retire_channel_destination(values: dict[str, Any]) -> dict[str, Any]:
    context = _channel_context(values, "retire")
    actor = _actor(values)
    current = _account_record(_channel_key(context))
    if current and (current["revision"] > context["destination"]["revision"] or current.get("user_id", actor) != actor):
        raise PluginError("This retirement is stale or belongs to another user.")
    _store(_channel_key(context), {"revision": context["destination"]["revision"], "retired": True})
    return {"retired": True}


def deliver_channel(values: dict[str, Any]) -> dict[str, Any]:
    try:
        context = _channel_context(values, "deliver")
        actor = _actor(values)
        record = _account_record(_channel_key(context))
        server = _channel_server(context)
        if (not record or record.get("retired") or record["revision"] != context["destination"]["revision"]
                or record.get("user_id") != actor or record.get("server_revision") != server["revision"]
                or context["server_revision"] != server["revision"]):
            raise PluginError("This configured channel revision is unavailable.")
        delivery = values.get("delivery")
        if (not isinstance(delivery, dict) or not isinstance(delivery.get("title"), str)
                or not isinstance(delivery.get("body"), str) or delivery.get("purpose", "notification") not in {"notification", "test"}):
            raise PluginError("Only ordinary public notifications can use a channel.")
        _check_channel(server["token"], server["guild_id"], record["channel_id"])
        if "contract_version" in delivery:
            return _deliver_rich(server["token"], record["channel_id"], delivery)
        content = f"**{delivery['title'][:250]}**\n{delivery['body']}"
        link = delivery.get("link")
        if isinstance(link, str) and link.startswith(("https://", "http://")):
            content += "\n" + link
        if len(content) > 1900:
            raise PluginError("This notification exceeds Discord message limits.")
        _send_channel(server["token"], record["channel_id"], content)
    except GatewayRequestError as exc:
        print("Discord channel gateway failure: " + exc.code, file=sys.stderr, flush=True)
        return {"success": False, "retryable": exc.code in {"unavailable", "rate_limited"}, "error": "discord_gateway_failed"}
    except DiscordTemporaryError:
        return {"success": False, "retryable": True, "error": "discord_temporarily_unavailable"}
    except PluginError as exc:
        # These local errors contain only static diagnostics, never token or API bodies.
        print("Discord channel delivery rejected: " + str(exc), file=sys.stderr, flush=True)
        return {"success": False, "retryable": False, "error": "discord_channel_unavailable"}
    except (KeyError, TypeError, ValueError) as exc:
        print("Discord channel configuration error: " + type(exc).__name__, file=sys.stderr, flush=True)
        return {"success": False, "retryable": False, "error": "discord_channel_unavailable"}
    return {"success": True, "retryable": False}


def edit_channel(values: dict[str, Any]) -> dict[str, Any]:
    """Apply a story revision to the message this channel destination sent earlier."""
    return deliver_channel(values)


def _register_provider() -> None:
    delay = 1
    while True:
        try:
            register_provider(
                PROVIDER_ID,
                "Discord Bot DM",
                "deliver",
                transport="plugin",
                definition={
                    "destinations": [
                        {
                            "kind": "discord_bot_dm",
                            "label": "Discord Bot DM",
                            "privacy": "PRIVATE",
                            "fields": [],
                        }
                    ],
                    "configure_action": "configure-destination",
                    "retire_action": "retire-destination",
                    "test_action": "test-dm",
                    "features": {"critical_supported": False, "multiple_destinations": False},
                },
            )
            register_provider(ACCOUNT_PROVIDER_ID, "Discord account DM", "deliver-account", transport="plugin", definition=ACCOUNT_DEFINITION)
            register_provider(CHANNEL_PROVIDER_ID, "Discord server channel", "deliver-channel", transport="plugin", definition=CHANNEL_DEFINITION)
            return
        except GatewayRequestError as exc:
            if exc.code != "unavailable":
                raise
            print("Waiting for the host gateway before registering Discord Bot DM.", file=sys.stderr, flush=True); time.sleep(delay); delay = min(delay * 2, 30)


def main() -> None:
    _register_provider()
    while True:
        time.sleep(3600)


def save_activity_oauth(values: dict[str, Any]) -> dict[str, Any]:
    """Reuse this bot's identity while keeping OAuth configuration plugin-owned."""
    _actor(values, admin=True)
    config = _bot_config()
    application_id = str(values.get("application_id", ""))
    client_secret = str(values.get("client_secret", "")).strip()
    allow_private = values.get("allow_private_channels", False)
    if type(allow_private) is not bool:
        raise PluginError("Choose whether private-channel Activities are allowed.")
    previous = _load("secrets/activity-oauth", {})
    if not client_secret and previous.get("application_id") == application_id:
        client_secret = previous.get("client_secret", "")
    if not _SNOWFLAKE.fullmatch(application_id) or not 16 <= len(client_secret) <= 256:
        raise PluginError("Enter the Discord application ID and OAuth client secret.")
    bot = _discord(config["token"], "GET", "/users/@me")
    if not isinstance(bot, dict) or bot.get("id") != application_id:
        raise PluginError("The Activity must use the same application as this configured bot.")
    _store("secrets/activity-oauth", {"application_id": application_id, "client_secret": client_secret,
                                     "allow_private_channels": allow_private})
    return {"configured": True, "application_id": application_id}


def activity_config(_values: dict[str, Any]) -> dict[str, Any]:
    config = _load("secrets/activity-oauth", {})
    bot = _load("secrets/bot-config", {})
    return {"application_id": config.get("application_id"),
            "allow_private_channels": config.get("allow_private_channels") is True,
            "configured": bool(config.get("client_secret") and bot.get("token"))}


def _activity_membership(subject: str, room: str) -> dict:
    config, oauth = _bot_config(), _load("secrets/activity-oauth", {})
    application_id = oauth.get("application_id")
    if (not isinstance(subject, str) or not _SNOWFLAKE.fullmatch(subject)
            or not isinstance(room, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", room)
            or not isinstance(application_id, str) or not _SNOWFLAKE.fullmatch(application_id)):
        raise PluginError("Invalid Activity identity or room.")
    instance = _discord(config["token"], "GET",
                        f"/applications/{application_id}/activity-instances/{quote(room, safe='')}")
    if (not isinstance(instance, dict) or instance.get("application_id") != application_id
            or instance.get("instance_id") != room or not isinstance(instance.get("users"), list)
            or subject not in instance["users"]):
        raise PluginError("Join this exact Discord Activity instance first.")
    location = instance.get("location")
    if not isinstance(location, dict) or not _SNOWFLAKE.fullmatch(str(location.get("channel_id", ""))):
        raise PluginError("Discord returned no valid Activity channel.")
    if location.get("kind") == "gc":
        if location.get("guild_id") != config["guild_id"]:
            raise PluginError("Join this bot's Activity in its configured server first.")
    elif location.get("kind") == "pc" and not location.get("guild_id"):
        if oauth.get("allow_private_channels") is not True:
            raise PluginError("The operator has not enabled Activities in DMs and group DMs.")
    else:
        raise PluginError("This Discord Activity location is not supported.")
    return {"verified": True, "subject": subject, "room": room}


def authenticate_activity(values: dict[str, Any]) -> dict[str, Any]:
    """OAuth identity and bot-verified membership; client-supplied names are never proof."""
    proof = values.get("proof", {})
    if not isinstance(proof, dict) or set(proof) != {"code", "instance_id"}:
        raise PluginError("The Activity must provide its OAuth authorization code and instance ID.")
    code = proof.get("code")
    if not isinstance(code, str) or not 1 <= len(code) <= 2048:
        raise PluginError("Invalid Discord authorization code.")
    oauth = _load("secrets/activity-oauth", {})
    if not oauth.get("client_secret"):
        raise PluginError("Configure Activity OAuth in the bot's administrator settings first.")
    response = request("network.request", "network.outbound", {
        "url": DISCORD_API + "/oauth2/token", "method": "POST",
        "headers": {"Content-Type": "application/x-www-form-urlencoded", "User-Agent": DISCORD_USER_AGENT},
        "text_body": urlencode({"client_id": oauth["application_id"],
                                "client_secret": oauth["client_secret"],
                                "grant_type": "authorization_code", "code": code}),
    })
    data = response.get("data", {})
    token = data.get("access_token") if isinstance(data, dict) else None
    if response.get("status") != 200 or not isinstance(token, str) or not token:
        raise PluginError("Discord sign-in failed. Close and relaunch the Activity to retry.")
    identity = request("network.request", "network.outbound", {
        "url": DISCORD_API + "/users/@me", "method": "GET",
        "headers": {"Authorization": "Bearer " + token, "User-Agent": DISCORD_USER_AGENT},
    })
    user = identity.get("data", {})
    if identity.get("status") != 200 or not isinstance(user, dict):
        raise PluginError("Discord could not verify your identity.")
    result = _activity_membership(user.get("id"), proof.get("instance_id"))
    return {**result, "display_name": str(user.get("global_name") or user.get("username") or "Participant")[:100],
            "account_name": str(user.get("username") or "Participant")[:100],
            "avatar_url": _avatar_url(user) or f"https://cdn.discordapp.com/embed/avatars/{(int(user['id']) >> 22) % 6}.png",
            "sdk_authentication": {"access_token": token}}


def revalidate_activity(values: dict[str, Any]) -> dict[str, Any]:
    return _activity_membership(values.get("subject"), values.get("room"))


if __name__ == "__main__":
    main()
