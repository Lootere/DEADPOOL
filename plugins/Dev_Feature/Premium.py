# This code has been modified by @Looteredev
# Please do not remove this credit
from datetime import timedelta, datetime, time
import pytz
from Script import script
from asyncio import sleep
from info import ADMINS, PREMIUM_LOGS, OWNER_USER_NAME, PREMIUM_PIC
from utils import get_seconds, get_premium_plans, format_premium_plans
from database.users_chats_db import db 
from pyrogram import Client, filters 
from pyrogram.errors.exceptions.bad_request_400 import MessageTooLong
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

async def check_expired_premium(client):
    last_dest_check = 0.0
    while 1:
        data = await db.get_expired(datetime.now())
        
        for user in data:
            user_id = user["id"]
            await db.remove_premium_access(user_id)
            try:
                user = await client.get_users(user_id)
                try:
                    await client.send_message(
                        chat_id=user_id,
                        text=f"<b><i>Hᴇʏ Tʜᴇʀᴇ {user.mention} 👋</i>\n\n<u>ʏᴏᴜʀ ᴘʀᴇᴍɪᴜᴍ ᴀᴄᴄᴇss ʜᴀs ᴇxᴘɪʀᴇᴅ ❗\nᴛʜᴀɴᴋ ʏᴏᴜ ꜰᴏʀ ᴜsɪɴɢ ᴏᴜʀ sᴇʀᴠɪᴄᴇ.</u>\n\nɪꜰ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴛᴀᴋᴇ ᴛʜᴇ ᴘʀᴇᴍɪᴜᴍ ᴀɢᴀɪɴ, ᴛʜᴇɴ ᴄʟɪᴄᴋ ᴏɴ ᴛʜᴇ /plans ꜰᴏʀ ᴛʜᴇ ᴅᴇᴛᴀɪʟs ᴏꜰ ᴛʜᴇ ᴘʟᴀɴs.</b>")
                except:
                    pass   
                await client.send_message(
                    PREMIUM_LOGS, 
                    text=f"<b>#PREMIUM_EXPIRED\n\nUsᴇʀ : {user.mention}\nUsᴇʀ Iᴅ : <code>{user_id}</code></b>"
                )
            except Exception as e:
                pass
            await sleep(0.5)

        # Feature 4: Reconcile VIP Destination subscriptions & send expiry reminders
        now_ts = datetime.now().timestamp()
        if now_ts - last_dest_check >= 60.0:
            last_dest_check = now_ts
            try:
                from Lootere.utils.subscription_manager import subscription_manager
                await subscription_manager.reconcile_expiries_and_reminders(client)
            except Exception:
                pass

        await sleep(1)
	    
@Client.on_message(filters.command("remove_premium") & filters.user(ADMINS))
async def remove_premium(client, message):
    if len(message.command) == 2:
        user_id = int(message.command[1])  # Convert the user_id to integer
        user = await client.get_users(user_id)
        if await db.remove_premium_access(user_id):
            await message.reply_text("ᴜꜱᴇʀ ʀᴇᴍᴏᴠᴇᴅ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ !")
            await client.send_message(
                chat_id=user_id,
                text=f"<b>ʜᴇʏ {user.mention},\n\nʏᴏᴜʀ ᴘʀᴇᴍɪᴜᴍ ᴀᴄᴄᴇss ʜᴀs ʙᴇᴇɴ ʀᴇᴍᴏᴠᴇᴅ.\nᴛʜᴀɴᴋ ʏᴏᴜ ꜰᴏʀ ᴜsɪɴɢ ᴏᴜʀ sᴇʀᴠɪᴄᴇ 😊\nᴄʟɪᴄᴋ ᴏɴ /plans ᴛᴏ ᴄʜᴇᴄᴋ ᴏᴜᴛ ᴏᴛʜᴇʀ ᴘʟᴀɴꜱ.</b>"
            )
        else:
            await message.reply_text("ᴜɴᴀʙʟᴇ ᴛᴏ ʀᴇᴍᴏᴠᴇ ᴜꜱᴇᴅ !\nᴀʀᴇ ʏᴏᴜ ꜱᴜʀᴇ, ɪᴛ ᴡᴀꜱ ᴀ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀ ɪᴅ ?")
    else:
        await message.reply_text("ᴜꜱᴀɢᴇ : /remove_premium user_id") 

@Client.on_message(filters.command("myplan"))
async def myplan(client, message):
    user = message.from_user.mention 
    user_id = message.from_user.id
    data = await db.get_user(message.from_user.id)  # Convert the user_id to integer
    if data and data.get("expiry_time"):
        expiry = data.get("expiry_time") 
        expiry_ist = expiry.astimezone(pytz.timezone("Asia/Kolkata"))
        expiry_str_in_ist = expiry.astimezone(pytz.timezone("Asia/Kolkata")).strftime("%d-%m-%Y\n⏱️ ᴇxᴘɪʀʏ ᴛɪᴍᴇ : %I:%M:%S %p")            
        current_time = datetime.now(pytz.timezone("Asia/Kolkata"))
        time_left = expiry_ist - current_time
            
        days = time_left.days
        hours, remainder = divmod(time_left.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
            
        # Format time left as a string
        time_left_str = f"{days} ᴅᴀʏꜱ, {hours} ʜᴏᴜʀꜱ, {minutes} ᴍɪɴᴜᴛᴇꜱ"
        await message.reply_text(f"⚜️ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀ ᴅᴀᴛᴀ :\n\n👤 ᴜꜱᴇʀ : {user}\n⚡ ᴜꜱᴇʀ ɪᴅ : <code>{user_id}</code>\n⏰ ᴛɪᴍᴇ ʟᴇꜰᴛ : {time_left_str}\n⌛️ ᴇxᴘɪʀʏ ᴅᴀᴛᴇ : {expiry_str_in_ist}")   
    else:
        await message.reply_text(f"ʜᴇʏ {user},\n\nʏᴏᴜ ᴅᴏ ɴᴏᴛ ʜᴀᴠᴇ ᴀɴʏ ᴀᴄᴛɪᴠᴇ ᴘʀᴇᴍɪᴜᴍ ᴘʟᴀɴs, ɪꜰ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴛᴀᴋᴇ ᴘʀᴇᴍɪᴜᴍ ᴛʜᴇɴ ᴄʟɪᴄᴋ ᴏɴ ʙᴇʟᴏᴡ ʙᴜᴛᴛᴏɴ 👇",
	reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💸 ᴄʜᴇᴄᴋᴏᴜᴛ ᴘʀᴇᴍɪᴜᴍ ᴘʟᴀɴꜱ 💸", callback_data='premium_pm')]]))			 

@Client.on_message(filters.command("get_premium") & filters.user(ADMINS))
async def get_premium(client, message):
    if len(message.command) == 2:
        user_id = int(message.command[1])
        user = await client.get_users(user_id)
        data = await db.get_user(user_id)  # Convert the user_id to integer
        if data and data.get("expiry_time"):
            expiry = data.get("expiry_time") 
            expiry_ist = expiry.astimezone(pytz.timezone("Asia/Kolkata"))
            expiry_str_in_ist = expiry.astimezone(pytz.timezone("Asia/Kolkata")).strftime("%d-%m-%Y\n⏱️ ᴇxᴘɪʀʏ ᴛɪᴍᴇ : %I:%M:%S %p")            
            # Calculate time difference
            current_time = datetime.now(pytz.timezone("Asia/Kolkata"))
            time_left = expiry_ist - current_time
            
            # Calculate days, hours, and minutes
            days = time_left.days
            hours, remainder = divmod(time_left.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            # Format time left as a string
            time_left_str = f"{days} days, {hours} hours, {minutes} minutes"
            await message.reply_text(f"⚜️ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀ ᴅᴀᴛᴀ :\n\n👤 ᴜꜱᴇʀ : {user.mention}\n⚡ ᴜꜱᴇʀ ɪᴅ : <code>{user_id}</code>\n⏰ ᴛɪᴍᴇ ʟᴇꜰᴛ : {time_left_str}\n⌛️ ᴇxᴘɪʀʏ ᴅᴀᴛᴇ : {expiry_str_in_ist}")
        else:
            await message.reply_text("ɴᴏ ᴀɴʏ ᴘʀᴇᴍɪᴜᴍ ᴅᴀᴛᴀ ᴏꜰ ᴛʜᴇ ᴡᴀꜱ ꜰᴏᴜɴᴅ ɪɴ ᴅᴀᴛᴀʙᴀꜱᴇ !")
    else:
        await message.reply_text("ᴜꜱᴀɢᴇ : /get_premium user_id")

@Client.on_message(filters.command("add_premium") & filters.user(ADMINS))
async def give_premium_cmd_handler(client, message):
    if len(message.command) == 4:
        time_zone = datetime.now(pytz.timezone("Asia/Kolkata"))
        current_time = time_zone.strftime("%d-%m-%Y\n⏱️ ᴊᴏɪɴɪɴɢ ᴛɪᴍᴇ : %I:%M:%S %p") 
        user_id = int(message.command[1])  # Convert the user_id to integer
        user = await client.get_users(user_id)
        time = message.command[2]+" "+message.command[3]
        seconds = await get_seconds(time)
        if seconds > 0:
            expiry_time = datetime.now() + timedelta(seconds=seconds)
            user_data = {"id": user_id, "expiry_time": expiry_time}  # Using "id" instead of "user_id"  
            await db.update_user(user_data)  # Use the update_user method to update or insert user data
            data = await db.get_user(user_id)
            expiry = data.get("expiry_time")   
            expiry_str_in_ist = expiry.astimezone(pytz.timezone("Asia/Kolkata")).strftime("%d-%m-%Y\n⏱️ ᴇxᴘɪʀʏ ᴛɪᴍᴇ : %I:%M:%S %p")         
            await message.reply_text(f"ᴘʀᴇᴍɪᴜᴍ ᴀᴅᴅᴇᴅ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ✅\n\n👤 ᴜꜱᴇʀ : {user.mention}\n⚡ ᴜꜱᴇʀ ɪᴅ : <code>{user_id}</code>\n⏰ ᴘʀᴇᴍɪᴜᴍ ᴀᴄᴄᴇꜱꜱ : <code>{time}</code>\n\n⏳ ᴊᴏɪɴɪɴɢ ᴅᴀᴛᴇ : {current_time}\n\n⌛️ ᴇxᴘɪʀʏ ᴅᴀᴛᴇ : {expiry_str_in_ist}", disable_web_page_preview=True)
            await client.send_message(
                chat_id=user_id,
                text=f"👋 ʜᴇʏ {user.mention},\nᴛʜᴀɴᴋ ʏᴏᴜ ꜰᴏʀ ᴘᴜʀᴄʜᴀꜱɪɴɢ ᴘʀᴇᴍɪᴜᴍ.\nᴇɴᴊᴏʏ !! ✨🎉\n\n⏰ ᴘʀᴇᴍɪᴜᴍ ᴀᴄᴄᴇꜱꜱ : <code>{time}</code>\n⏳ ᴊᴏɪɴɪɴɢ ᴅᴀᴛᴇ : {current_time}\n\n⌛️ ᴇxᴘɪʀʏ ᴅᴀᴛᴇ : {expiry_str_in_ist}", disable_web_page_preview=True              
            )    
            await client.send_message(PREMIUM_LOGS, text=f"#Added_Premium\n\n👤 ᴜꜱᴇʀ : {user.mention}\n⚡ ᴜꜱᴇʀ ɪᴅ : <code>{user_id}</code>\n⏰ ᴘʀᴇᴍɪᴜᴍ ᴀᴄᴄᴇꜱꜱ : <code>{time}</code>\n\n⏳ ᴊᴏɪɴɪɴɢ ᴅᴀᴛᴇ : {current_time}\n\n⌛️ ᴇxᴘɪʀʏ ᴅᴀᴛᴇ : {expiry_str_in_ist}", disable_web_page_preview=True)
                    
        else:
            await message.reply_text("Invalid time format. Please use '1 day for days', '1 hour for hours', or '1 min for minutes', or '1 month for months' or '1 year for year'")
    else:
        await message.reply_text("Usage : /add_premium user_id time (e.g., '1 day for days', '1 hour for hours', or '1 min for minutes', or '1 month for months' or '1 year for year')")

@Client.on_message(filters.command("premium_users") & filters.user(ADMINS))
async def premium_user(client, message):
    aa = await message.reply_text("<i>ꜰᴇᴛᴄʜɪɴɢ...</i>")
    new = f"⚜️ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀꜱ ʟɪꜱᴛ :\n\n"
    user_count = 1
    users = await db.get_all_users()
    async for user in users:
        data = await db.get_user(user['id'])
        if data and data.get("expiry_time"):
            expiry = data.get("expiry_time") 
            expiry_ist = expiry.astimezone(pytz.timezone("Asia/Kolkata"))
            expiry_str_in_ist = expiry.astimezone(pytz.timezone("Asia/Kolkata")).strftime("%d-%m-%Y\n⏱️ ᴇxᴘɪʀʏ ᴛɪᴍᴇ : %I:%M:%S %p")            
            current_time = datetime.now(pytz.timezone("Asia/Kolkata"))
            time_left = expiry_ist - current_time
            days = time_left.days
            hours, remainder = divmod(time_left.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            time_left_str = f"{days} days, {hours} hours, {minutes} minutes"	 
            new += f"{user_count}. {(await client.get_users(user['id'])).mention}\n👤 ᴜꜱᴇʀ ɪᴅ : {user['id']}\n⏳ ᴇxᴘɪʀʏ ᴅᴀᴛᴇ : {expiry_str_in_ist}\n⏰ ᴛɪᴍᴇ ʟᴇꜰᴛ : {time_left_str}\n"
            user_count += 1
        else:
            pass
    try:    
        await aa.edit_text(new)
    except MessageTooLong:
        with open('usersplan.txt', 'w+') as outfile:
            outfile.write(new)
        await message.reply_document('usersplan.txt', caption="Paid Users:")


@Client.on_message(filters.command("plans"))
async def plan(client, message):
    btn = [[
        InlineKeyboardButton("🔲 Qʀ ", callback_data='qr_info'),
        InlineKeyboardButton("💳 Uᴘɪ ", callback_data='upi_info')],
	[InlineKeyboardButton("❌ ᴄʟᴏꜱᴇ ❌", callback_data="close_data")
    ]]
    await message.reply_photo(
        photo=PREMIUM_PIC,
        caption=format_premium_plans(await get_premium_plans()),
        reply_markup=InlineKeyboardMarkup(btn),
        parse_mode="html",
    )


# ======================================================================
# Feature 4: Premium Hub + VIP Destination Subscriptions (Admin & User)
# ======================================================================

import logging
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


@Client.on_message(filters.command("dest_list") & filters.user(ADMINS))
async def list_destinations_cmd(client, message):
    from Lootere.utils.subscription_manager import subscription_manager
    dests = subscription_manager.dest_mgr.list_destinations()
    if not dests:
        return await message.reply_text("<b>No VIP destinations configured.</b>\nUse /dest_add to add one.")
    lines = ["<b>VIP DESTINATIONS LIST</b>\n"]
    for d in dests:
        status_icon = "ACTIVE" if d.get("status") == "active" else "DISABLED"
        lines.append(
            f"• <b>{d.get('name')}</b> (<code>{d.get('id')}</code>)\n"
            f"  ├ <b>Type:</b> <code>{d.get('type')}</code>\n"
            f"  ├ <b>Chat ID:</b> <code>{d.get('chat_id')}</code>\n"
            f"  └ <b>Status:</b> <code>{status_icon}</code>\n"
        )
    lines.append("<i>Commands: /dest_add, /dest_del, /dest_toggle, /dest_test</i>")
    await message.reply_text("\n".join(lines))


@Client.on_message(filters.command("dest_add") & filters.user(ADMINS))
async def add_destination_cmd(client, message):
    from Lootere.utils.subscription_manager import subscription_manager
    if len(message.command) < 4:
        return await message.reply_text(
            "<b>Usage:</b> <code>/dest_add &lt;group|channel&gt; &lt;chat_id&gt; &lt;name&gt;</code>\n"
            "<b>Example:</b> <code>/dest_add channel -1002148604082 VIP Movies</code>"
        )
    dest_type = message.command[1].lower()
    if dest_type not in ["group", "channel"]:
        return await message.reply_text("Destination type must be either 'group' or 'channel'.")
    try:
        chat_id = int(message.command[2])
    except ValueError:
        return await message.reply_text("Invalid chat_id. Must be integer (e.g. -100...).")
    name = " ".join(message.command[3:])
    dest_id = f"dest_{dest_type}_{abs(chat_id)}"

    success, msg = await subscription_manager.dest_mgr.add_destination(
        dest_id=dest_id, name=name, chat_id=chat_id, dest_type=dest_type
    )
    perm_test = await subscription_manager.test_destination_permissions(client, dest_id)
    if not perm_test.get("success"):
        msg += f"\n\n<b>Warning:</b> Bot could not verify permissions in chat ({perm_test.get('error')}). Please ensure bot is admin with invite & ban rights."
    await message.reply_text(msg)


@Client.on_message(filters.command("dest_del") & filters.user(ADMINS))
async def del_destination_cmd(client, message):
    from Lootere.utils.subscription_manager import subscription_manager
    if len(message.command) != 2:
        return await message.reply_text("<b>Usage:</b> <code>/dest_del &lt;dest_id&gt;</code>")
    dest_id = message.command[1]
    success, msg = await subscription_manager.dest_mgr.remove_destination(dest_id)
    await message.reply_text(msg)


@Client.on_message(filters.command("dest_toggle") & filters.user(ADMINS))
async def toggle_destination_cmd(client, message):
    from Lootere.utils.subscription_manager import subscription_manager
    if len(message.command) != 2:
        return await message.reply_text("<b>Usage:</b> <code>/dest_toggle &lt;dest_id&gt;</code>")
    dest_id = message.command[1]
    success, msg = await subscription_manager.dest_mgr.toggle_destination(dest_id)
    await message.reply_text(msg)


@Client.on_message(filters.command("dest_test") & filters.user(ADMINS))
async def test_destination_cmd(client, message):
    from Lootere.utils.subscription_manager import subscription_manager
    if len(message.command) != 2:
        return await message.reply_text("<b>Usage:</b> <code>/dest_test &lt;dest_id&gt;</code>")
    dest_id = message.command[1]
    res = await subscription_manager.test_destination_permissions(client, dest_id)
    if not res.get("success"):
        return await message.reply_text(f"<b>Failed to test destination:</b> {res.get('error')}")
    await message.reply_text(
        f"<b>DESTINATION PERMISSIONS REPORT</b>\n\n"
        f"• <b>Destination:</b> <code>{dest_id}</code>\n"
        f"• <b>Chat ID:</b> <code>{res.get('chat_id')}</code>\n"
        f"• <b>Bot Status:</b> <code>{res.get('status')}</code>\n"
        f"• <b>Can Invite Users:</b> <code>{'YES' if res.get('can_invite_users') else 'NO'}</code>\n"
        f"• <b>Can Ban/Remove Members:</b> <code>{'YES' if res.get('can_restrict_members') else 'NO'}</code>"
    )


@Client.on_message(filters.command("vip_plan_list") & filters.user(ADMINS))
async def list_vip_plans_cmd(client, message):
    from Lootere.utils.subscription_manager import subscription_manager
    plans = subscription_manager.dest_mgr.list_plans()
    if not plans:
        return await message.reply_text("No VIP plans configured. Use /vip_plan_add.")
    lines = ["<b>VIP PLANS LIST</b>\n"]
    for p in plans:
        dests = ", ".join(p.get("destinations", []))
        lines.append(
            f"• <b>{p.get('name')}</b> (<code>{p.get('id')}</code>)\n"
            f"  ├ <b>Destinations:</b> <code>{dests}</code>\n"
            f"  ├ <b>Duration:</b> <code>{p.get('duration_days')} Days</code>\n"
            f"  └ <b>Price:</b> <code>{p.get('price')}</code>\n"
        )
    await message.reply_text("\n".join(lines))


@Client.on_message(filters.command("vip_plan_add") & filters.user(ADMINS))
async def add_vip_plan_cmd(client, message):
    from Lootere.utils.subscription_manager import subscription_manager
    if len(message.command) < 5:
        return await message.reply_text(
            "<b>Usage:</b> <code>/vip_plan_add &lt;plan_id&gt; &lt;duration_days&gt; &lt;dest_ids_comma_separated&gt; &lt;price&gt; &lt;plan_name&gt;</code>\n"
            "<b>Example:</b> <code>/vip_plan_add gold 30 dest_group1,dest_channel1 ₹199/month Gold VIP</code>"
        )
    plan_id = message.command[1].lower()
    try:
        duration_days = int(message.command[2])
    except ValueError:
        return await message.reply_text("duration_days must be an integer.")
    dest_ids = [d.strip() for d in message.command[3].split(",") if d.strip()]
    price = message.command[4]
    plan_name = " ".join(message.command[5:]) if len(message.command) > 5 else plan_id.title()

    success, msg = await subscription_manager.dest_mgr.add_plan(
        plan_id=plan_id,
        name=plan_name,
        destination_ids=dest_ids,
        duration_days=duration_days,
        price=price,
    )
    await message.reply_text(msg)


@Client.on_message(filters.command("vip_plan_del") & filters.user(ADMINS))
async def del_vip_plan_cmd(client, message):
    from Lootere.utils.subscription_manager import subscription_manager
    if len(message.command) != 2:
        return await message.reply_text("<b>Usage:</b> <code>/vip_plan_del &lt;plan_id&gt;</code>")
    plan_id = message.command[1]
    success, msg = await subscription_manager.dest_mgr.remove_plan(plan_id)
    await message.reply_text(msg)


@Client.on_message(filters.command("vip_add") & filters.user(ADMINS))
async def vip_add_cmd(client, message):
    from Lootere.utils.subscription_manager import subscription_manager
    if len(message.command) < 3:
        return await message.reply_text(
            "<b>Usage:</b> <code>/vip_add &lt;user_id&gt; &lt;plan_id&gt; [duration_days]</code>\n"
            "<b>Example:</b> <code>/vip_add 123456789 gold 30</code>"
        )
    try:
        user_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("Invalid user_id.")
    plan_id = message.command[2].lower()
    plan = subscription_manager.dest_mgr.get_plan(plan_id)
    if not plan:
        return await message.reply_text(f"Plan '{plan_id}' does not exist. Check /vip_plan_list.")
    duration_days = int(message.command[3]) if len(message.command) > 3 else plan.get("duration_days", 30)

    success, msg, sub = await subscription_manager.activate_subscription(
        user_id=user_id,
        plan_id=plan_id,
        duration_days=duration_days,
        admin_id=message.from_user.id,
    )
    if not success:
        return await message.reply_text(f"Failed: {msg}")

    # Generate fresh invites for user
    await subscription_manager.generate_user_invites(client, user_id)

    # Notify admin
    await message.reply_text(f"<b>VIP Subscription Activated</b>\n\n{msg}")

    # Notify user with button to view links
    try:
        btn = InlineKeyboardMarkup([[
            InlineKeyboardButton("VIEW INVITE LINKS", callback_data="dest_invites")
        ]])
        await client.send_message(
            chat_id=user_id,
            text=(
                f"<b>VIP Community Membership Activated!</b>\n\n"
                f"• <b>Plan:</b> {plan.get('name')}\n"
                f"• <b>Duration:</b> {duration_days} Days\n"
                f"• <b>Expiry:</b> {sub['expiry_time'].strftime('%d-%m-%Y %I:%M %p')} IST\n\n"
                f"Click the button below to access your unique private channel & group invite links."
            ),
            reply_markup=btn,
        )
    except Exception as e:
        await message.reply_text(f"<b>Notice:</b> Could not DM user {user_id}: {e}")

    # Log to PREMIUM_LOGS
    try:
        await client.send_message(
            PREMIUM_LOGS,
            f"<b>#VIP_DESTINATION_ADDED</b>\n\n"
            f"• <b>User ID:</b> <code>{user_id}</code>\n"
            f"• <b>Plan:</b> {plan.get('name')}\n"
            f"• <b>Duration:</b> {duration_days} Days\n"
            f"• <b>Admin:</b> {message.from_user.mention}"
        )
    except Exception:
        pass


@Client.on_message(filters.command("vip_renew") & filters.user(ADMINS))
async def vip_renew_cmd(client, message):
    from Lootere.utils.subscription_manager import subscription_manager
    if len(message.command) < 2:
        return await message.reply_text(
            "<b>Usage:</b> <code>/vip_renew &lt;user_id&gt; [duration_days]</code>\n"
            "<b>Note:</b> Only admin-approved renewals extend or restore subscriptions."
        )
    try:
        user_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("Invalid user_id.")
    days = int(message.command[2]) if len(message.command) > 2 else None

    success, msg, sub = await subscription_manager.renew_subscription(
        user_id=user_id, duration_days=days, admin_id=message.from_user.id
    )
    if not success:
        return await message.reply_text(f"Failed: {msg}")

    await message.reply_text(f"<b>VIP Renewal Approved</b>\n\n{msg}")

    try:
        btn = InlineKeyboardMarkup([[
            InlineKeyboardButton("VIEW INVITE LINKS", callback_data="dest_invites")
        ]])
        await client.send_message(
            chat_id=user_id,
            text=(
                f"<b>VIP Membership Renewed!</b>\n\n"
                f"Admin has approved your renewal.\n"
                f"• <b>New Expiry:</b> {sub['expiry_time'].strftime('%d-%m-%Y %I:%M %p')} IST"
            ),
            reply_markup=btn,
        )
    except Exception:
        pass


@Client.on_message(filters.command("vip_remove") & filters.user(ADMINS))
async def vip_remove_cmd(client, message):
    from Lootere.utils.subscription_manager import subscription_manager
    if len(message.command) != 2:
        return await message.reply_text("<b>Usage:</b> <code>/vip_remove &lt;user_id&gt;</code>")
    try:
        user_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("Invalid user_id.")

    sub = await subscription_manager.get_user_subscription(user_id)
    if not sub:
        return await message.reply_text(f"No subscription found for user {user_id}.")

    dest_ids = sub.get("destinations", [])
    for dest_id in dest_ids:
        dest = subscription_manager.dest_mgr.get_destination(dest_id)
        if dest and client:
            try:
                await client.ban_chat_member(dest["chat_id"], user_id)
                await client.unban_chat_member(dest["chat_id"], user_id)
            except Exception as e:
                logger.error(f"Failed to remove user {user_id} from {dest_id}: {e}")

    await subscription_manager.cancel_subscription(user_id)
    await message.reply_text(f"User {user_id} VIP membership cancelled and removed from destinations.")

    try:
        await client.send_message(
            chat_id=user_id,
            text="<b>VIP Access Cancelled</b>\n\nYour VIP group/channel membership has been revoked by admin."
        )
    except Exception:
        pass


@Client.on_message(filters.command("vip_users") & filters.user(ADMINS))
async def vip_users_cmd(client, message):
    from Lootere.utils.subscription_manager import subscription_manager
    subs = await subscription_manager.list_all_active_subscriptions()
    if not subs:
        return await message.reply_text("No active VIP destination subscribers.")

    now = datetime.now(IST)
    lines = ["<b>ACTIVE VIP SUBSCRIBERS</b>\n"]
    for i, s in enumerate(subs, 1):
        uid = s.get("user_id")
        plan_name = s.get("plan_name", "VIP")
        exp = s.get("expiry_time")
        if exp and exp.tzinfo is None:
            exp = IST.localize(exp)
        if exp and exp > now:
            diff = exp - now
            time_left = f"{diff.days}d {diff.seconds // 3600}h"
        else:
            time_left = "Expired"
        exp_str = exp.strftime("%d-%m-%Y") if exp else "Unknown"
        lines.append(f"{i}. User <code>{uid}</code> | {plan_name} | Left: {time_left} (Exp: {exp_str})")

    await message.reply_text("\n".join(lines))


@Client.on_message(filters.command("myvip"))
async def myvip_cmd(client, message):
    from Lootere.utils.subscription_manager import (
        subscription_manager,
        format_my_plans_text,
        build_my_plans_keyboard,
    )
    user_id = message.from_user.id
    dest_sub = await subscription_manager.get_subscription(user_id)
    destinations = subscription_manager.dest_mgr._destinations
    text = format_my_plans_text(None, dest_sub, destinations)
    has_sub = bool(dest_sub and dest_sub.get("status") == "active")
    reply_markup = build_my_plans_keyboard(has_dest_sub=has_sub)
    await message.reply_text(text, reply_markup=reply_markup, parse_mode="html")


# ======================================================================
# Manual Payment Screenshot Approval System (User Upload & Admin Commands)
# ======================================================================

@Client.on_message(filters.private & (filters.photo | filters.document) & filters.incoming)
async def handle_payment_screenshot_upload(client, message):
    from Lootere.utils.payment_manager import (
        payment_manager,
        format_review_message_caption,
        build_admin_review_keyboard,
    )
    user_id = message.from_user.id
    selection = payment_manager.get_user_plan_selection(user_id)
    if not selection:
        return

    file_id = None
    if message.photo:
        file_id = message.photo.file_id
    elif message.document:
        mime = getattr(message.document, "mime_type", "") or ""
        if not (mime.startswith("image/") or mime == "application/pdf"):
            return await message.reply_text(
                "Please upload a valid payment screenshot image or PDF document."
            )
        file_id = message.document.file_id

    if not file_id:
        return

    ok, msg, req = await payment_manager.create_payment_request(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        product_type=selection["product_type"],
        plan_id=selection["plan_id"],
        plan_name=selection["plan_name"],
        duration_days=selection["duration_days"],
        amount=selection["amount"],
        screenshot_file_id=file_id,
    )
    if not ok:
        return await message.reply_text(msg)

    req_id = req["request_id"]
    await message.reply_text(
        f"<b>Payment Proof Received!</b>\n\n"
        f"• <b>Request ID:</b> <code>{req_id}</code>\n"
        f"• <b>Plan:</b> {req['plan_name']} ({req['duration_days']} Days)\n"
        f"• <b>Status:</b> <code>PENDING ADMIN VERIFICATION</code>\n\n"
        f"You will be notified automatically here as soon as an admin verifies and approves your payment."
    )

    review_chat_id = payment_manager.review_channel_id or PREMIUM_LOGS
    if review_chat_id:
        caption = format_review_message_caption(req)
        keyboard = build_admin_review_keyboard(req_id)
        try:
            if message.photo:
                sent = await client.send_photo(
                    chat_id=review_chat_id,
                    photo=file_id,
                    caption=caption,
                    reply_markup=keyboard,
                )
            else:
                sent = await client.send_document(
                    chat_id=review_chat_id,
                    document=file_id,
                    caption=caption,
                    reply_markup=keyboard,
                )
            req["review_message_id"] = sent.id
            req["review_chat_id"] = review_chat_id
            if payment_manager.db is not None:
                await payment_manager.db["payment_requests"].update_one(
                    {"request_id": req_id},
                    {"$set": {"review_message_id": sent.id, "review_chat_id": review_chat_id}},
                )
        except Exception as e:
            logger.error(f"Failed to forward payment screenshot {req_id} to review channel {review_chat_id}: {e}")


@Client.on_message(filters.private & filters.command("cancel"))
async def cancel_payment_flow_cmd(client, message):
    from Lootere.utils.payment_manager import payment_manager
    uid = message.from_user.id
    had_user = payment_manager.get_user_plan_selection(uid) is not None
    had_admin = payment_manager.get_admin_state(uid) is not None
    payment_manager.clear_user_plan_selection(uid)
    payment_manager.clear_admin_state(uid)
    if had_user or had_admin:
        await message.reply_text("Active payment / review input flow has been cancelled.")
    else:
        await message.reply_text("No active payment flow to cancel.")


@Client.on_message(filters.command("set_pay_channel") & filters.user(ADMINS))
async def set_pay_channel_cmd(client, message):
    from Lootere.utils.payment_manager import payment_manager
    if len(message.command) != 2:
        return await message.reply_text("<b>Usage:</b> <code>/set_pay_channel &lt;channel_id&gt;</code>")
    try:
        ch_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("Invalid channel_id. Must be an integer (e.g. -100...).")

    perm = await payment_manager.test_review_channel_permissions(client, ch_id)
    if not perm.get("success"):
        return await message.reply_text(
            f"<b>Could not verify bot access to channel <code>{ch_id}</code>:</b>\n{perm.get('error')}\n\n"
            f"Make sure the bot is an administrator in the review channel."
        )

    payment_manager.set_review_channel(ch_id)
    await db.set_setting("PAYMENT_LOG_CHANNEL", ch_id)
    await message.reply_text(
        f"<b>Payment Review Channel Configured!</b>\n\n"
        f"• <b>Channel:</b> {perm.get('title')}\n"
        f"• <b>Chat ID:</b> <code>{ch_id}</code>\n"
        f"• <b>Can Post Screenshots:</b> <code>{'YES' if perm.get('can_post_messages') else 'NO'}</code>"
    )


@Client.on_message(filters.command("test_pay_channel") & filters.user(ADMINS))
async def test_pay_channel_cmd(client, message):
    from Lootere.utils.payment_manager import payment_manager
    ch_id = payment_manager.review_channel_id or PREMIUM_LOGS
    if not ch_id:
        return await message.reply_text("No payment review channel configured. Use /set_pay_channel.")
    perm = await payment_manager.test_review_channel_permissions(client, ch_id)
    if not perm.get("success"):
        return await message.reply_text(f"<b>Review Channel Test Failed:</b> {perm.get('error')}")
    await message.reply_text(
        f"<b>PAYMENT REVIEW CHANNEL STATUS</b>\n\n"
        f"• <b>Title:</b> {perm.get('title')}\n"
        f"• <b>Chat ID:</b> <code>{ch_id}</code>\n"
        f"• <b>Bot Status:</b> <code>{perm.get('status')}</code>\n"
        f"• <b>Can Post Messages:</b> <code>{'YES' if perm.get('can_post_messages') else 'NO'}</code>"
    )


@Client.on_message(filters.command("add_reviewer") & filters.user(ADMINS))
async def add_reviewer_cmd(client, message):
    from Lootere.utils.payment_manager import payment_manager
    if len(message.command) != 2:
        return await message.reply_text("<b>Usage:</b> <code>/add_reviewer &lt;user_id&gt;</code>")
    try:
        rev_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("Invalid user_id.")
    if rev_id not in payment_manager.authorized_reviewers:
        payment_manager.authorized_reviewers.append(rev_id)
    await message.reply_text(f"User <code>{rev_id}</code> added to authorized payment reviewers.")


@Client.on_message(filters.command("remove_reviewer") & filters.user(ADMINS))
async def remove_reviewer_cmd(client, message):
    from Lootere.utils.payment_manager import payment_manager
    if len(message.command) != 2:
        return await message.reply_text("<b>Usage:</b> <code>/remove_reviewer &lt;user_id&gt;</code>")
    try:
        rev_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("Invalid user_id.")
    if rev_id in payment_manager.authorized_reviewers:
        payment_manager.authorized_reviewers.remove(rev_id)
    await message.reply_text(f"User <code>{rev_id}</code> removed from authorized payment reviewers.")


@Client.on_message(filters.command("pending_payments") & filters.user(ADMINS))
async def pending_payments_cmd(client, message):
    from Lootere.utils.payment_manager import payment_manager
    pending = await payment_manager.list_pending_requests()
    if not pending:
        return await message.reply_text("No pending payment requests.")
    lines = ["<b>PENDING PAYMENT REQUESTS</b>\n"]
    for i, r in enumerate(pending, 1):
        lines.append(
            f"{i}. <code>{r['request_id']}</code> | User: <code>{r['user_id']}</code> | "
            f"{r['product_type']} ({r['plan_name']}) | {r['amount']}"
        )
    await message.reply_text("\n".join(lines))


