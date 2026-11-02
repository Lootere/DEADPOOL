# This code has been modified by @Looteredev
# Please do not remove this credit
import logging
import pyrogram
from pyrogram import Client, filters
from info import LOG_CHANNEL

logger = logging.getLogger(__name__)

@Client.on_chat_join_request()
async def auto_accept_request(client, chat_member_update):
    chat_id = chat_member_update.chat.id
    user_id = chat_member_update.from_user.id

    try:
        from Lootere.utils.subscription_manager import subscription_manager
        # Check if chat is a VIP destination
        dest = None
        for d in subscription_manager.dest_mgr._destinations.values():
            if d.get("chat_id") == chat_id:
                dest = d
                break

        if dest:
            # VIP destination: enforce identity validation & subscription check
            is_valid = await subscription_manager.is_user_subscribed_to_destination(user_id, chat_id)
            if not is_valid:
                logger.warning(f"Unauthorized join attempt: User {user_id} tried to join VIP {dest.get('name')} ({chat_id})")
                try:
                    await client.send_message(
                        LOG_CHANNEL,
                        f"<b>#VIP_UNAUTHORIZED_JOIN</b>\n\n"
                        f"• <b>User:</b> <code>{user_id}</code>\n"
                        f"• <b>Chat:</b> {dest.get('name')} (<code>{chat_id}</code>)\n"
                        f"• <b>Status:</b> Admission blocked (No active subscription)."
                    )
                except Exception:
                    pass
                return

            # Approved subscriber
            await client.approve_chat_join_request(chat_id, user_id)
            await subscription_manager.verify_and_record_join(user_id, chat_id)
            try:
                await client.send_message(
                    user_id,
                    f"<b>Welcome to {dest.get('name')}!</b>\n\n"
                    f"Aapki VIP join request approve ho gayi hai. Enjoy unlimited movies and series!"
                )
            except Exception:
                pass
            return

        # Regular non-VIP chats: existing auto join behavior
        await client.get_chat_member(chat_id, client.me.id) 
        await client.approve_chat_join_request(chat_id, user_id)

    except Exception as e:
        logger.error(f"Error handling join request for user {user_id} in {chat_id}: {e}")

