import os
import sys
import time
import requests
import random
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event 
import asyncio
import datetime
import logging
from gzip import decompress 

# Set up logging for better diagnostics and console output
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Try to import websocket-client, install if not found
try:
    from websocket import create_connection
except ImportError:
    logger.info("جاري تثبيت مكتبة 'websocket-client'...")
    os.system(f'{sys.executable} -m pip install websocket-client')
    from websocket import create_connection

# Try to import requests, install if not found
try:
    import requests
except ImportError:
    logger.info("جاري تثبيت مكتبة 'requests'...")
    os.system(f'{sys.executable} -m pip install requests')
    from requests import post as requests_post # Import requests.post directly for synchronous use

# Telegram Bot Library Imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler

# --- Global Variables for Bot State and Tool Data ---
# Bot token for THIS bot (integrated directly)
BOT_TOKEN_FOR_THIS_APP = "8126269492:AAElcXAV7eypooqyi0CKTOhFZoXKWNadeik"

# Admin chat ID for notifications (provided by user)
ADMIN_CHAT_ID = 7530878932

# In-memory set to track users who started the bot in this session (for admin notifications)
known_users = set()

current_user_chat_id = None 
tool_running = False 
executor = None # ThreadPoolExecutor will be initialized and used for blocking I/O
stop_event = Event() 

success_count = 0
failed_count = 0
retry_count = 0
accounts_list = [] 
proxies_list = [] # List to store parsed proxy data

# Variable to store the message ID of the live statistics message, for editing
stats_message_id = None
stats_update_task = None # Reference to the periodic stats update asyncio task

# ConversationHandler states for guiding user input
ASKING_TARGET_BOT_TOKEN, ASKING_TARGET_CHAT_ID, ASKING_PROXIES = range(3)

# --- Proxy Parsing Function ---
def parse_proxy_string(proxy_str: str):
    """
    Parses a proxy string (e.g., 'ip:port' or 'user:pass@ip:port') 
    and returns a dictionary with host, port, and optional auth.
    """
    proxy_str = proxy_str.strip()
    if not proxy_str:
        return None

    # Check if the input looks like a Telegram Chat ID (numbers, possibly starting with -)
    if proxy_str.replace('-', '').isdigit() and len(proxy_str) <= 15: # Telegram Chat IDs are typically up to 15 digits
        logger.warning(f"تم إدخال قيمة تبدو كمعرف دردشة تيليجرام بدلاً من بروكسي: {proxy_str}")
        return {'is_chat_id': True, 'value': proxy_str} # Special return to indicate chat ID like input

    parts = proxy_str.split('@')
    auth = None
    host_port_str = parts[-1]

    if len(parts) == 2: # Authentication info is present (user:pass@host:port)
        user_pass_str = parts[0]
        user_pass_split = user_pass_str.split(':')
        if len(user_pass_split) == 2:
            auth = (user_pass_split[0], user_pass_split[1])
        else:
            logger.warning(f"تنسيق توثيق البروكسي غير صالح: {user_pass_str}")
            return None # Invalid auth format
    elif len(parts) > 2: # More than one '@' implies invalid format
        logger.warning(f"تنسيق بروكسي غير صالح (أكثر من علامة '@'): {proxy_str}")
        return None

    # Extract host and port
    host_port_split = host_port_str.split(':')
    if len(host_port_split) == 2:
        host = host_port_split[0]
        try:
            port = int(host_port_split[1])
        except ValueError:
            logger.warning(f"منفذ البروكسي غير صالح: {host_port_split[1]}")
            return None # Invalid port
        return {'host': host, 'port': port, 'auth': auth, 'is_chat_id': False}
    else:
        logger.warning(f"تنسيق البروكسي غير صالح (host:port): {host_port_str}")
        return None # Invalid host:port format

# --- Core Account Registration Logic (Blocking Function for ThreadPoolExecutor) ---
def run_account_registration_blocking_task(target_bot_token: str, target_chat_id: str, proxy_data: dict = None):
    """
    Attempts to register one account via WebSocket.
    This is the 'blocking' part that will be run in a ThreadPoolExecutor.
    """
    global success_count, failed_count, retry_count, accounts_list

    username = random.choice('qwertyuiooasdfghjklzxcvpbnm') + \
               ''.join(random.choices(list('qwertyuioasdfghjklzxcvbnpm1234567890'), k=16))
    
    con = None
    response_text = "" # Initialize response_text for logging
    try:
        ws_options = {
            "header": {"app": "com.safeum.android", "host": None, "remoteIp": "195.13.182.213",
                       "remotePort": str(8080), "sessionId": "b6cbb22d-06ca-41ff-8fda-c0ddeb148195",
                       "time": "2024-04-11 11:00:00", "url": "wss://51.79.208.190/Auth"},
            "sslopt": {"cert_reqs": 0} # Disable SSL certificate verification (use with caution)
        }

        if proxy_data:
            ws_options['http_proxy_host'] = proxy_data['host']
            ws_options['http_proxy_port'] = proxy_data['port']
            if proxy_data['auth']:
                ws_options['http_proxy_auth'] = proxy_data['auth']
            logger.debug(f"Attempting connection via proxy: {proxy_data.get('host')}:{proxy_data.get('port')}")
        
        # Add timeout to create_connection to prevent indefinite hanging
        con = create_connection("wss://195.13.182.213/Auth", timeout=15, **ws_options)

        payload = {
            "action": "Register", "subaction": "Desktop", "locale": "en_GB", "gmt": "+05",
            "password": {"m1x": "5b2d79b243d1ff4db8be0b1a8f2fe690204b4a344e78a2b4b1507d5665b81929", "m1y": "363e088b28d1d8d304b65dc83b73bfaf492a6a6ba84b9cc2edf2698c2ce2a33a", "m2": "57476060be56982f4be6fa2514b3dc715c4ba2148a5fa946aef0db49b7a2275f", "iv": "88e78f8ecefe378a18d22e5735a6e491", "message": "3f6070524fce7d28283588753a1548d1319824bdd479b259720bd42fd7c138089dc5926fd98ba4b246c5dd9dad844c1a49d6c7cc832fcc081d6bcbcc15cfdc8161a07231ea0ac6a25c00fee6ce99cbd2"},
            "magicword": {"m1x": "82fcbc07b9d0968f34d9864cfad9b43a3f29c519f3561d7c445af65069e00d61", "m1y": "d326f75f67a8653dad381add5de1dde22b81689380fda06b34e8810db53aafa0", "m2": "d877f3d7a8ac8b101dd8f9aa439515a78ae1cdcfddd3cb2cf7a3b1e92ee234dc", "iv": "c7e23ca31448ff2438a139d1cab9321e", "message": "33b5fc02ff044baca05769b569ebb045"},
            "magicwordhint": "0000", "login": str(username), "devicename": "Xiaomi 23106RN0DA", "softwareversion": "1.1.0.1548",
            "nickname": "jahs58absga", "os": "AND", "deviceuid": "63e6d773ee99664d", "devicepushuid": "*eQUS3f0lSA6d2PBl3p54d4:APA91bGf-W7kFATks4gNHB6igovWHXkf7H5hmODLs5Q6lBZ8NEXQbJcgnSfSBnuyNCI9-ujPrJ67xZXqgp0vLQd3mPp4ANlitdDEHp1LJpa9wWja36OisIMgqTysUsEaAc5QFBrnfSa",
            "osversion": "and_13.0.0", "id": "475467112"
        }
        con.send(json.dumps(payload))
        # Receive data with a timeout (socket timeout from create_connection should apply)
        response_data = con.recv() 
        
        # Decompress gzip response if it's compressed, as per original tool
        try:
            gzip_data = decompress(response_data)
            response_text = gzip_data.decode('utf-8')
        except Exception:
            # If not gzip or decoding fails, try direct decode
            response_text = response_data.decode('utf-8', errors='ignore')

        if '"status":"Success"' in response_text:
            success_count += 1
            account_info = f"{username}:fati"
            accounts_list.append(account_info)
            
            # Send the successfully caught account to the target bot/chat with elegant code block formatting
            try:
                requests_post(
                    f"https://api.telegram.org/bot{target_bot_token}/sendMessage",
                    json={"chat_id": target_chat_id, "text": f"✅ *تم صيد حساب بنجاح:* ✅\n```\n{account_info}\n```", "parse_mode": "Markdown"},
                    timeout=5 # Add a timeout to prevent hanging
                )
            except Exception as e:
                logger.error(f"خطأ أثناء إرسال الحساب إلى البوت المستهدف: {e}")

            logger.info(f"Safeum Response (Success): {response_text}") # Log successful response
            return True, username
        else:
            failed_count += 1
            logger.info(f"Safeum Response (Failure): {response_text}") # Log failed response
            return False, None
    except Exception as e:
        retry_count += 1
        logger.error(f"خطأ في الاتصال أو تسجيل الحساب (قد يكون بسبب البروكسي أو انتهاء المهلة أو رفض الخادم): {e} | Safeum Response: {response_text}")
        return False, None
    finally:
        try:
            if con:
                con.close()
        except Exception as e:
            logger.error(f"خطأ أثناء إغلاق اتصال WebSocket: {e}")

async def tool_main_loop(application: Application, target_bot_token: str, target_chat_id: str, proxies: list):
    """
    Main loop for the account registration tool.
    Runs as an asyncio task within the bot's main event loop.
    This function continuously attempts to register accounts.
    """
    global success_count, failed_count, retry_count, current_user_chat_id, stop_event, executor

    logger.info("بدء تشغيل أداة تسجيل الحسابات.")
    
    # This loop will run as long as tool_running is True and stop_event is not set
    while tool_running and not stop_event.is_set():
        current_proxy = None
        if proxies: # If proxies are available, choose one randomly
            current_proxy = random.choice(proxies)

        # Run the blocking task in ThreadPoolExecutor and await it asynchronously
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            executor, run_account_registration_blocking_task, target_bot_token, target_chat_id, current_proxy
        )

        # The condition here is based on total attempts, not just success, to ensure it doesn't run indefinitely
        if success_count + failed_count + retry_count >= 2990: 
            await application.bot.send_message(
                chat_id=current_user_chat_id, 
                text="🎉 تم الوصول إلى الحد الأقصى للمحاولات أو تم إنشاء عدد كبير من الحسابات. الأداة ستتوقف الآن."
            )
            tool_running = False
            break 

        await asyncio.sleep(0.001) # Very, very small delay for maximum speed

    # Final messages when the tool stops
    final_termination_message_text = ""
    if stop_event.is_set():
        final_termination_message_text = "🛑 *تم إيقاف الأداة بناءً على طلبك.*"
    else:
        final_termination_message_text = "✅ *الأداة توقفت عن العمل.*"
    
    await application.bot.send_message(
        chat_id=current_user_chat_id, 
        text=final_termination_message_text,
        parse_mode='Markdown'
    )

    if accounts_list:
        # Format each account info elegantly for the final summary
        formatted_accounts = [f"• `{acc}`" for acc in accounts_list]
        final_accounts_message_text = "✨ *ملخص الحسابات التي تم صيدها:* (أُرسلت أيضاً إلى البوت المستهدف)\n\n" + "\n".join(formatted_accounts)
        
        if len(final_accounts_message_text) > 4096: # Telegram message length limit
            final_accounts_message_text = final_accounts_message_text[:4000] + "\n...(القائمة مختصرة لتجاوز حد الرسالة)"
        
        await application.bot.send_message(
            chat_id=current_user_chat_id, 
            text=final_accounts_message_text,
            parse_mode='Markdown'
        )
    
    stop_event.clear()
    logger.info("توقفت حلقة أداة تسجيل الحسابات الرئيسية.")

async def send_periodic_stats(application: Application):
    """
    Sends/Edits the periodic statistics message.
    Runs as a separate asyncio task.
    """
    global success_count, failed_count, retry_count, current_user_chat_id, stats_message_id, tool_running
    
    # Ensure initial message is sent if tool starts (and chat_id is available)
    if stats_message_id is None and current_user_chat_id:
        initial_status_message_text = (
            f"📊 *جاري بدء عملية الصيد...*\n"
            f"> ✅ *تم صيد:* `0` حساب\n"
            f"> ❌ *فشل:* `0` محاولة\n"
            f"> 🔄 *إعادة محاولة:* `0`\n"
            f"> 📈 *اجمالي المحاولات:* `0`\n"
            f"> 🕒 *وقت التحديث:* `{datetime.datetime.now().strftime('%H:%M:%S')}`"
        )
        try:
            sent_message = await application.bot.send_message(
                chat_id=current_user_chat_id,
                text=initial_status_message_text,
                parse_mode='Markdown'
            )
            stats_message_id = sent_message.message_id
        except Exception as e:
            logger.error(f"فشل في إرسال رسالة الإحصائيات الأولية: {e}")
            stats_message_id = None # Reset if failed

    # Loop for periodic updates as long as the tool is running and there's a valid chat_id and message_id
    while tool_running and current_user_chat_id: # Loop as long as tool is running and chat_id is available
        await asyncio.sleep(0.8) # Update frequency: every 0.8 seconds

        # Only attempt to edit if stats_message_id is still valid
        if stats_message_id:
            updated_status_message_text = (
                f"📊 *لوحة تحكم الصيد المباشرة:* 🔥\n"
                f"> _تحديث الوقت:_ `{datetime.datetime.now().strftime('%H:%M:%S')}`\n\n"
                f"> ✅ *الحسابات المصيدة:* `{success_count}`\n"
                f"> ❌ *الحسابات الفاشلة:* `{failed_count}`\n"
                f"> 🔄 *إعادة المحاولات:* `{retry_count}`\n"
                f"> 📈 *إجمالي المحاولات:* `{success_count + failed_count + retry_count}`\n\n"
                f"> *سرعة صاروخية!* البوت يعمل بكفاءة لا مثيل لها."
            )
            try:
                await application.bot.edit_message_text(
                    chat_id=current_user_chat_id,
                    message_id=stats_message_id,
                    text=updated_status_message_text,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"خطأ في تعديل رسالة الإحصائيات (قد يكون بسبب انتهاء المهلة أو حذف الرسالة): {e}")
                # Fallback: if editing fails, try to send a new message and update the ID
                try:
                    sent_message = await application.bot.send_message(
                        chat_id=current_user_chat_id,
                        text=updated_status_message_text,
                        parse_mode='Markdown'
                    )
                    stats_message_id = sent_message.message_id 
                except Exception as e_fallback:
                    logger.error(f"خطأ في إرسال رسالة إحصائيات جديدة كبديل: {e_fallback}")
                    stats_message_id = None # Indicate no active stats message if fallback also fails

    logger.info("توقفت مهمة تحديث الإحصائيات الدورية.")


# --- Telegram Bot Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    global current_user_chat_id, known_users, stats_message_id
    
    # Reset stats message ID on new start
    stats_message_id = None

    if update.effective_chat:
        current_user_chat_id = update.effective_chat.id
        user_id = update.effective_user.id # Get the actual user ID
        
        # Notify admin about new user
        # Only notify if it's not the admin themselves AND the user hasn't been known in this session
        if user_id != ADMIN_CHAT_ID: # Don't notify if admin starts the bot
            # Check if user is known in this session (in-memory)
            if user_id not in known_users:
                known_users.add(user_id) # Add user_id to the set
                user_info = update.effective_user
                username_str = f"@{user_info.username}" if user_info.username else "غير متوفر"
                full_name = user_info.full_name if user_info.full_name else "غير متوفر"
                
                admin_notification_message_text = (
                    f"🔔 *إشعار مستخدم جديد دخل البوت!* 🔔\n\n"
                    f"> 👤 *الاسم الكامل:* `{full_name}`\n"
                    f"> 🏷️ *اسم المستخدم:* `{username_str}`\n"
                    f"> 🆔 *معرف المستخدم (ID):* `{user_id}`\n"
                    f"> 💬 *معرف الدردشة (Chat ID):* `{current_user_chat_id}`\n"
                    f"> ⏰ *وقت الدخول:* `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
                    f"*💡 ملاحظة:* هذا الإحصاء للمستخدمين في هذه الجلسة الحالية. للعد الكلي الدائم، يلزم قاعدة بيانات."
                )
                try:
                    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_notification_message_text, parse_mode='Markdown')
                    logger.info(f"Admin notified about new user: {current_user_chat_id}")
                except Exception as e:
                    logger.error(f"خطأ أثناء إرسال إشعار الأدمن: {e}")

    else:
        logger.error("لم يتم العثور على effective_chat في أمر /start.")
        return ConversationHandler.END

    welcome_message_text = """
👋 *مرحباً بك في بوت أداة تسجيل حسابات سافيوم!* (الإصدار 2025.06.27.1080) 👋

أنا هنا لمساعدتك في أتمتة عملية تسجيل الحسابات.
"""

    developer_info_text = """
*معلومات المطور:*
🧑‍💻 *المبرمج الرئيسي:* [@NETRO_GZ](https://t.me/NETRO_GZ)
📢 *قناة المطور:* [@abdoshvw](https://t.me/abdoshvw)
"""

    usage_instructions_text = """
*تعليمات الاستخدام:*
1.  أرسل /start لبدء الإعداد.
2.  زودني *بتوكن البوت الآخر* الذي تريد إرسال الحسابات المصيدة إليه.
3.  زودني *بمعرف (ID) الدردشة* الذي تريد إرسال الحسابات إليه (يمكنك الحصول عليه من `@userinfobot`).
4.  زودني *بقائمة البروكسيات* (كل بروكسي في سطر جديد).
    * *مثال:* `ip:port` أو `user:pass@ip:port`
    * *إذا لم يكن لديك بروكسيات أو لا تريد استخدامها، يمكنك فقط إرسال `لا` أو تخطي هذه الخطوة.*
5.  اضغط على زر "🔥 تشغيل الأداة" للبدء.
6.  لإيقاف الأداة، اضغط على زر "🛑 إيقاف الأداة".
7.  للتحقق من أنني أعمل، أرسل /ping.
"""

    # CORRECTED URLS for InlineKeyboardButtons - NO MARKDOWN IN URL PARAMETER
    keyboard = [
        [InlineKeyboardButton("🧑‍💻 التواصل مع المطور", url="https://t.me/NETRO_GZ")],
        [InlineKeyboardButton("📢 قناة المطور", url="https://t.me/abdoshvw")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        welcome_message_text + developer_info_text + usage_instructions_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    
    await update.message.reply_text(
        "الآن، لكي أبدأ العمل، الرجاء إرسال *توكن البوت الآخر* الذي تريدني أن أرسل له الحسابات المصيدة (النتائج).",
        parse_mode='Markdown'
    )
    return ASKING_TARGET_BOT_TOKEN

async def receive_target_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    target_bot_token = update.message.text.strip()
    if not target_bot_token or len(target_bot_token) < 30 or ":" not in target_bot_token: 
        await update.message.reply_text("❌ هذا لا يبدو وكأنه توكن بوت صالح. الرجاء إدخال توكن صحيح.\n\nتذكر أن التوكن يبدأ عادةً بأرقام يتبعها نقطتان رأسيتان (مثال: `123456789:ABCDEF...`).", parse_mode='Markdown')
        return ASKING_TARGET_BOT_TOKEN

    context.user_data['target_bot_token'] = target_bot_token
    await update.message.reply_text(
        "✅ توكن البوت المستهدف تم استلامه بنجاح!\n\n"
        "الآن، الرجاء إرسال *معرف (ID) الدردشة* الذي تريد أن ترسل إليه الحسابات المصيدة باستخدام البوت الآخر.\n"
        "يمكنك الحصول على معرف الدردشة الخاص بك من خلال بوت مثل `@userinfobot`.\n\n"
        "*(معرف الدردشة يكون عادةً مجموعة من الأرقام، وقد تبدأ بعلامة ناقص '-').*",
        parse_mode='Markdown'
    )
    return ASKING_TARGET_CHAT_ID

async def receive_target_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        target_chat_id_str = update.message.text.strip()
        target_chat_id = int(target_chat_id_str)
        context.user_data['target_chat_id'] = target_chat_id

        await update.message.reply_text(
            f"✅ تم ضبط معرف الدردشة المستهدف: `{target_chat_id}`",
            parse_mode='Markdown'
        )
        
        await update.message.reply_text(
            "جيد جداً! الخطوة الأخيرة هي تزويدي بقائمة البروكسيات.\n\n"
            "*الرجاء إرسال البروكسيات الخاصة بك، كل بروكسي في سطر منفصل.*\n"
            "يمكن أن تكون على الشكل التالي:\n"
            "`ip:port`\n"
            "`user:pass@ip:port`\n\n"
            "*إذا لم يكن لديك بروكسيات أو لا تريد استخدامها، يمكنك فقط إرسال `لا` أو تخطي هذه الخطوة لعدم استخدامها (قد يكون الصيد أبطأ أو يتعرض للحظر أسرع).*",
            parse_mode='Markdown'
        )
        return ASKING_PROXIES # Transition to proxy asking state
    except ValueError:
        await update.message.reply_text("❌ هذا لا يبدو وكأنه معرف دردشة صالح. الرجاء إرسال معرف دردشة صحيح (أرقام فقط، قد تحتوي على علامة ناقص في البداية).", parse_mode='Markdown')
        return ASKING_TARGET_CHAT_ID
    except Exception as e:
        logger.error(f"Error in receive_target_chat_id: {e}")
        await update.message.reply_text(f"❌ حدث خطأ غير متوقع: {e}\nالرجاء المحاولة مرة أخرى أو التواصل مع المطور.", parse_mode='Markdown')
        return ASKING_TARGET_CHAT_ID

async def receive_proxies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    global proxies_list
    user_input = update.message.text.strip()
    
    if user_input.lower() == 'لا' or not user_input:
        proxies_list = []
        await update.message.reply_text("ℹ️ لم يتم إدخال بروكسيات. ستعمل الأداة بدون بروكسيات.")
    else:
        raw_proxies = user_input.split('\n')
        parsed_current_proxies = []
        
        # Check if the input looks like a Telegram Chat ID or just a simple number
        # This is a robust check to ensure it's not interpreted as a proxy
        if user_input.replace('-', '').isdigit() and len(user_input) <= 15:
            await update.message.reply_text(
                "⚠️ *تنبيه:* يبدو أن ما أدخلته هو معرف دردشة تيليجرام وليس بروكسي.\n"
                "الرجاء إما إدخال بروكسيات بتنسيق `ip:port` أو `user:pass@ip:port`، أو أرسل `لا` لتخطي هذه الخطوة.",
                parse_mode='Markdown'
            )
            return ASKING_PROXIES # Stay in the same state to allow re-entry of proxies

        for proxy_str in raw_proxies:
            stripped_proxy_str = proxy_str.strip()
            if stripped_proxy_str:
                parsed = parse_proxy_string(stripped_proxy_str)
                # Check if it was a chat_id like string (from parse_proxy_string's special return)
                if parsed and 'is_chat_id' in parsed and parsed['is_chat_id']:
                    await update.message.reply_text(
                        f"⚠️ *تنبيه:* السلسلة `{parsed['value']}` تبدو كمعرف دردشة، وليست بروكسي صالحاً.\n"
                        "سيتم تجاهلها. يرجى التأكد من إدخال بروكسيات بتنسيق `ip:port` أو `user:pass@ip:port`.",
                        parse_mode='Markdown'
                    )
                    continue # Skip this invalid proxy entry
                elif parsed:
                    parsed_current_proxies.append(parsed)
        
        if parsed_current_proxies:
            proxies_list = parsed_current_proxies
            await update.message.reply_text(f"✅ تم استلام وتحليل {len(proxies_list)} بروكسي بنجاح.")
        else:
            proxies_list = []
            await update.message.reply_text("❌ لم يتم العثور على أي بروكسيات صالحة في إدخالك. يرجى التأكد من التنسيق (host:port أو user:pass@host:port). ستعمل الأداة بدون بروكسيات.", parse_mode='Markdown')

    keyboard = [[InlineKeyboardButton("🔥 تشغيل الأداة", callback_data="run_tool")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🎉 *تم إعداد البوت بالكامل!* أنت الآن جاهز لبدء العمل.\n"
        "اضغط على زر 'تشغيل الأداة' لبدء عملية تسجيل الحسابات.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return ConversationHandler.END

async def run_tool_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global tool_running, executor, success_count, failed_count, retry_count, accounts_list, stop_event, proxies_list, stats_message_id, stats_update_task

    query = update.callback_query
    await query.answer()

    target_bot_token = context.user_data.get('target_bot_token')
    target_chat_id = context.user_data.get('target_chat_id')

    if not target_bot_token or not target_chat_id:
        await query.edit_message_text(
            "⚠️ لم يتم تعيين توكن البوت المستهدف أو معرف الدردشة المستهدف بعد.\n"
            "الرجاء البدء بـ /start وتزويد المعلومات المطلوبة لتهيئة البوت."
            , parse_mode='Markdown'
        )
        return

    if tool_running:
        await query.edit_message_text("⚙️ الأداة تعمل بالفعل!")
        return

    success_count = 0
    failed_count = 0
    retry_count = 0
    accounts_list = []
    stop_event.clear()
    stats_message_id = None # Reset stats message ID for a new run

    tool_running = True
    executor = ThreadPoolExecutor(max_workers=1000) # Increased workers for maximum speed

    try:
        # Explicitly declare global to avoid NameError in some environments
        # although Python's scope rules generally handle this for top-level functions.
        global tool_main_loop, send_periodic_stats

        # Start the main tool loop and the periodic stats update task
        context.application.create_task(tool_main_loop(context.application, target_bot_token, target_chat_id, proxies_list))
        stats_update_task = context.application.create_task(send_periodic_stats(context.application))
    except NameError as ne:
        logger.error(f"FATAL ERROR: Function not defined: {ne}. This indicates a serious environment issue.")
        await query.message.reply_text(
            "🚨 *خطأ فادح في تشغيل الأداة!* 🚨\n\n"
            "يبدو أن هناك مشكلة خطيرة في بيئة التشغيل الخاصة بك (مثل Pydroid3 أو Terminal).\n"
            "هذا الخطأ يعني أن أجزاء أساسية من الكود لا يتم تحميلها بشكل صحيح.\n\n"
            "*الحل الوحيد هو إجراء إعادة تعيين كاملة لبيئة التشغيل الخاصة بك:*\n"
            "1.  **أغلق Pydroid3 تماماً (بالإيقاف الإجباري ومسح البيانات كما شرحت سابقاً) ثم أعد تشغيل هاتفك.**\n"
            "2.  **احفظ الكود في ملف بايثون *جديد تماماً باسم لم تستخدمه من قبل***.\n"
            "3.  **شغل الملف الجديد.**\n\n"
            "إذا استمر الخطأ بعد هذه الخطوات، يرجى التواصل مع المطور، فهذا يشير إلى مشكلة خارج نطاق الكود."
            , parse_mode='Markdown'
        )
        tool_running = False
        return # Stop execution if a critical NameError occurs

    keyboard = [[InlineKeyboardButton("🛑 إيقاف الأداة", callback_data="stop_tool")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "🚀 جاري بدء تشغيل الأداة...\n"
        "سترى تحديثات الحالة هنا، وسترسل الحسابات المصيدة إلى البوت والمعرف اللذين حددتهما."
        , reply_markup=reply_markup, parse_mode='Markdown'
    )

async def stop_tool_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global tool_running, executor, stop_event, stats_message_id, stats_update_task

    query = update.callback_query
    await query.answer()

    if not tool_running:
        await query.edit_message_text("ℹ️ الأداة ليست قيد التشغيل حالياً.")
        return

    tool_running = False
    stop_event.set()

    if stats_update_task: # Cancel the stats update task if it's running
        stats_update_task.cancel()
        stats_update_task = None
    stats_message_id = None # Reset stats message ID on stop

    keyboard = [[InlineKeyboardButton("🔥 تشغيل الأداة", callback_data="run_tool")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "⏳ إرسال إشارة إيقاف للأداة. قد يستغرق الأمر لحظات حتى تتوقف العمليات الجارية وتصلك رسالة التأكيد النهائية.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await update.message.reply_text(f"🏓 بونج! أنا أعمل بشكل جيد. الوقت الحالي: `{current_time}`", parse_mode='Markdown')

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    global stats_message_id, tool_running, stop_event, stats_update_task
    
    if tool_running: # If tool is running, attempt to stop it
        tool_running = False
        stop_event.set()
        if stats_update_task:
            stats_update_task.cancel()
            stats_update_task = None

    stats_message_id = None # Reset stats message ID on cancel

    await update.message.reply_text(
        "🚫 تم إلغاء العملية.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔥 تشغيل الأداة", callback_data="run_tool")]])
    )
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"❌ حدث خطأ: {context.error} في التحديث: {update}")
    
    if update and update.effective_chat:
        try:
            # Send simplified error to user for general errors, not the specific NameError
            if not isinstance(context.error, NameError): 
                await update.effective_chat.send_message("🚨 عذرًا، حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى لاحقًا أو التواصل مع المطور للمساعدة.")
        except Exception as e:
            logger.error(f"خطأ أثناء محاولة إرسال رسالة الخطأ للمستخدم: {e}")

def main() -> None:
    application = Application.builder().token(BOT_TOKEN_FOR_THIS_APP).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            ASKING_TARGET_BOT_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_target_bot_token)],
            ASKING_TARGET_CHAT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_target_chat_id)],
            ASKING_PROXIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_proxies)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(run_tool_callback, pattern="^run_tool$"))
    application.add_handler(CallbackQueryHandler(stop_tool_callback, pattern="^stop_tool$"))
    application.add_handler(CommandHandler("ping", ping_command))
    
    application.add_error_handler(error_handler)

    logger.info("✨ البوت يعمل الآن... اضغط Ctrl-C لإيقافه من الكونسول (هذه الرسالة تظهر لك فقط في بيئة التشغيل).")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True) 

if __name__ == '__main__':
    main()

