import asyncio
import json
import os
import smtplib
import ssl
import logging
import threading
import time
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from flask import Flask

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

BOT_TOKEN = "8225315835:AAGIYp2P7zAxItcwfTyEIxEwSuGCx1L1Y6w"
DATA_FILE = "bot_data.json"
MAX_DAILY = 500
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

STATE_IDLE = None
STATE_SET_EMAIL = "set_email"
STATE_SET_COUNT = "set_count"
STATE_SET_SUBJECT = "set_subject"
STATE_SET_CONTENT = "set_content"
STATE_SET_SUPPORT = "set_support"
STATE_ADD_PHOTO = "add_photo"

stop_flags = set()
SMTP_SEM = asyncio.Semaphore(30)

flask_app = Flask(__name__)


@flask_app.route("/")
def health():
    return "OK", 200


@flask_app.route("/ping")
def ping():
    return "pong", 200


def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT)


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user(user_id):
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "emails": [],
            "subject": None,
            "content": None,
            "support": None,
            "photo": None,
            "send_count": 1,
            "daily_sent": {},
        }
        save_data(data)
    return data[uid]


def save_user(user_id, user_data_dict):
    data = load_data()
    data[str(user_id)] = user_data_dict
    save_data(data)


def main_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("تعيين عدد الارسال", callback_data="set_count"),
                InlineKeyboardButton("ايميلاتي", callback_data="email_menu"),
            ],
            [
                InlineKeyboardButton("المواضيع", callback_data="set_subject"),
                InlineKeyboardButton("الكلايش", callback_data="set_content"),
            ],
            [
                InlineKeyboardButton("الدعم", callback_data="set_support"),
            ],
            [
                InlineKeyboardButton("حذف صورة", callback_data="delete_photo"),
                InlineKeyboardButton("اضافة صورة", callback_data="add_photo"),
            ],
            [
                InlineKeyboardButton("بدء الارسال", callback_data="start_send"),
            ],
        ]
    )


def back_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("رجوع", callback_data="back_main")]]
    )


def stop_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⏹ إيقاف الارسال", callback_data="stop_send")]]
    )


def email_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("تعيين", callback_data="add_email")],
            [InlineKeyboardButton("حذف", callback_data="del_email_menu")],
            [InlineKeyboardButton("عرض الايميلات", callback_data="view_emails")],
            [InlineKeyboardButton("رجوع", callback_data="back_main")],
        ]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = STATE_IDLE
    await update.message.reply_text(
        "اهلاً بك في بوت رفع خارجي",
        reply_markup=main_menu_keyboard(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "back_main":
        context.user_data["state"] = STATE_IDLE
        await query.edit_message_text(
            "اهلاً بك في بوت رفع خارجي",
            reply_markup=main_menu_keyboard(),
        )

    elif data == "email_menu":
        context.user_data["state"] = STATE_IDLE
        await query.edit_message_text(
            "اختر الإجراء المطلوب لإدارة حسابات البريد الإلكتروني:",
            reply_markup=email_menu_keyboard(),
        )

    elif data == "add_email":
        context.user_data["state"] = STATE_SET_EMAIL
        await query.edit_message_text(
            "أرسل الإيميل وكلمة مرور (التطبيقات) كالتالي:\n\n"
            "email1@gmail.com:xojs sowo xowb xibs",
            reply_markup=back_keyboard(),
        )

    elif data == "del_email_menu":
        user = get_user(user_id)
        if not user["emails"]:
            await query.edit_message_text(
                "لا توجد ايميلات مسجلة.", reply_markup=email_menu_keyboard()
            )
            return
        keyboard = []
        for i, em in enumerate(user["emails"]):
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"❌ {em['email']}", callback_data=f"delidx_{i}"
                    )
                ]
            )
        keyboard.append([InlineKeyboardButton("رجوع", callback_data="email_menu")])
        await query.edit_message_text(
            "اختر الايميل المراد حذفه:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif data.startswith("delidx_"):
        idx = int(data.split("_")[1])
        user = get_user(user_id)
        if idx < len(user["emails"]):
            removed = user["emails"].pop(idx)
            save_user(user_id, user)
            await query.edit_message_text(
                f"✅ تم حذف الايميل: {removed['email']}",
                reply_markup=email_menu_keyboard(),
            )
        else:
            await query.edit_message_text(
                "خطأ في الحذف.", reply_markup=email_menu_keyboard()
            )

    elif data == "view_emails":
        user = get_user(user_id)
        if not user["emails"]:
            await query.edit_message_text(
                "لا توجد ايميلات مسجلة.", reply_markup=email_menu_keyboard()
            )
            return
        text = "الإيميلات المسجلة لديك:\n\n"
        for i, em in enumerate(user["emails"], 1):
            text += (
                f"{i}. الإيميل: {em['email']}\n"
                f"كلمة المرور: {em['password']}\n\n"
            )
        await query.edit_message_text(text, reply_markup=back_keyboard())

    elif data == "set_count":
        user = get_user(user_id)
        if not user["emails"]:
            await query.edit_message_text(
                "⚠️ يجب تعيين ايميل أولاً قبل تحديد عدد الارسال.",
                reply_markup=back_keyboard(),
            )
            return
        context.user_data["state"] = STATE_SET_COUNT
        total_max = MAX_DAILY * len(user["emails"])
        await query.edit_message_text(
            f"أرسل عدد البلاغات المراد ارسالها\n"
            f"(لديك {len(user['emails'])} ايميل، الحد الأقصى {total_max} بلاغ يومياً):",
            reply_markup=back_keyboard(),
        )

    elif data == "set_subject":
        context.user_data["state"] = STATE_SET_SUBJECT
        await query.edit_message_text(
            "أرسل موضوع البلاغ:",
            reply_markup=back_keyboard(),
        )

    elif data == "set_content":
        context.user_data["state"] = STATE_SET_CONTENT
        await query.edit_message_text(
            "أرسل نص (كلايش) البلاغ المراد ارساله:",
            reply_markup=back_keyboard(),
        )

    elif data == "set_support":
        context.user_data["state"] = STATE_SET_SUPPORT
        await query.edit_message_text(
            "أرسل الان الدعم كالتالي:\n"
            "abuse@telegram.org\n"
            "stopCA@telegram.org",
            reply_markup=back_keyboard(),
        )

    elif data == "add_photo":
        context.user_data["state"] = STATE_ADD_PHOTO
        await query.edit_message_text(
            "أرسل الصورة المراد اضافتها في البلاغ:",
            reply_markup=back_keyboard(),
        )

    elif data == "delete_photo":
        user = get_user(user_id)
        user["photo"] = None
        save_user(user_id, user)
        await query.edit_message_text(
            "✅ تم حذف الصورة.", reply_markup=main_menu_keyboard()
        )

    elif data == "stop_send":
        stop_flags.add(user_id)
        await query.edit_message_text("⏹ جاري إيقاف الارسال...")

    elif data == "start_send":
        await handle_start_send(query, context, user_id)


async def send_with_key(sender_email, sender_password, to_email, subject, content, photo_data, key):
    result = await send_email(sender_email, sender_password, to_email, subject, content, photo_data)
    return result, key


async def handle_start_send(query, context, user_id):
    user = get_user(user_id)

    missing = []
    if not user["emails"]:
        missing.append("• ايميل المرسل (من قائمة ايميلاتي)")
    if not user["subject"]:
        missing.append("• موضوع البلاغ")
    if not user["content"]:
        missing.append("• نص البلاغ (الكلايش)")
    if not user["support"]:
        missing.append("• ايميل الدعم المستهدف")

    if missing:
        await query.edit_message_text(
            "⚠️ يجب تعيين التالي أولاً:\n\n" + "\n".join(missing),
            reply_markup=back_keyboard(),
        )
        return

    today = str(date.today())
    daily_sent = user.get("daily_sent", {})

    available_emails = []
    blocked_emails = []
    for em in user["emails"]:
        key = f"{em['email']}_{today}"
        sent = daily_sent.get(key, 0)
        if sent >= MAX_DAILY:
            blocked_emails.append(em["email"])
        else:
            available_emails.append(em)

    if not available_emails:
        total_sent = sum(
            daily_sent.get(f"{em['email']}_{today}", 0) for em in user["emails"]
        )
        text = (
            "❌ تم ايقاف العمليه بسبب وصول جميع الايميلات الى الحد اليومي\n\n"
            f"• عدد ايميلات الشد: {len(blocked_emails)}\n"
            f"• عدد الايميلات المحظورة: {len(blocked_emails)}\n\n"
            f"• تم الارسال: {total_sent}\n"
            "• تم الفشل: 0"
        )
        await query.edit_message_text(text, reply_markup=back_keyboard())
        return

    send_count = user.get("send_count", 1)
    stop_flags.discard(user_id)

    photo_data = None
    if user.get("photo"):
        try:
            photo_file = await context.bot.get_file(user["photo"])
            photo_data = await photo_file.download_as_bytearray()
        except Exception as e:
            logger.error(f"Photo download error: {e}")

    num = len(available_emails)
    base = send_count // num
    extra = send_count % num

    all_tasks = []
    email_keys = []

    for i, em in enumerate(available_emails):
        key = f"{em['email']}_{today}"
        sent_today = daily_sent.get(key, 0)
        remaining = MAX_DAILY - sent_today
        alloc = base + (1 if i < extra else 0)
        to_send = min(alloc, remaining)
        for _ in range(to_send):
            all_tasks.append(
                asyncio.create_task(
                    send_with_key(
                        em["email"],
                        em["password"],
                        user["support"],
                        user["subject"],
                        user["content"],
                        photo_data,
                        key,
                    )
                )
            )
            email_keys.append(key)

    progress_msg = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"🚀 جاري الارسال إلى {user['support']}...\n\n• تم الارسال: 0\n• تم الفشل: 0",
        reply_markup=stop_keyboard(),
    )

    sent_count = 0
    fail_count = 0
    last_edit = 0
    auth_failed_emails = set()

    for future in asyncio.as_completed(all_tasks):
        if user_id in stop_flags:
            for t in all_tasks:
                if not t.done():
                    t.cancel()
            break

        try:
            result, key = await future
        except asyncio.CancelledError:
            break
        except Exception:
            fail_count += 1
            continue

        if result is True:
            sent_count += 1
            daily_sent[key] = daily_sent.get(key, 0) + 1
        elif result == "auth_error":
            fail_count += 1
            email_name = key.rsplit("_", 1)[0]
            auth_failed_emails.add(email_name)
        else:
            fail_count += 1

        now = time.time()
        if now - last_edit >= 1.0:
            last_edit = now
            try:
                await progress_msg.edit_text(
                    f"🚀 جاري الارسال إلى {user['support']}...\n\n"
                    f"• تم الارسال: {sent_count}\n"
                    f"• تم الفشل: {fail_count}",
                    reply_markup=stop_keyboard(),
                )
            except Exception:
                pass

    user["daily_sent"] = daily_sent
    save_user(user_id, user)

    stopped = user_id in stop_flags
    stop_flags.discard(user_id)

    newly_blocked = [
        em["email"]
        for em in user["emails"]
        if daily_sent.get(f"{em['email']}_{today}", 0) >= MAX_DAILY
    ]

    if auth_failed_emails:
        failed_list = "\n".join(f"• {e}" for e in auth_failed_emails)
        final_text = (
            f"❌ كلمة مرور خاطئة للايميلات التالية:\n{failed_list}\n\n"
            "تأكد من تفعيل كلمة مرور التطبيقات في إعدادات Gmail.\n\n"
            f"• تم الارسال: {sent_count}\n"
            f"• تم الفشل: {fail_count}"
        )
    elif stopped:
        final_text = (
            f"⏹ تم إيقاف الارسال\n\n"
            f"• تم الارسال: {sent_count}\n"
            f"• تم الفشل: {fail_count}"
        )
    elif newly_blocked and len(newly_blocked) == len(user["emails"]):
        final_text = (
            "❌ تم ايقاف العمليه بسبب وصول جميع الايميلات الى الحد اليومي\n\n"
            f"• عدد ايميلات الشد: {len(newly_blocked)}\n"
            f"• عدد الايميلات المحظورة: {len(newly_blocked)}\n\n"
            f"• تم الارسال: {sent_count}\n"
            f"• تم الفشل: {fail_count}"
        )
    else:
        final_text = (
            f"✅ اكتمل الارسال\n\n"
            f"• تم الارسال: {sent_count}\n"
            f"• تم الفشل: {fail_count}"
        )

    try:
        await progress_msg.edit_text(final_text, reply_markup=back_keyboard())
    except Exception:
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=final_text,
            reply_markup=back_keyboard(),
        )


def _smtp_send(sender_email, sender_password, to_email, subject, content, photo_data):
    sender_password = sender_password.replace(" ", "")
    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(content, "plain", "utf-8"))

    if photo_data:
        img = MIMEImage(bytes(photo_data))
        img.add_header("Content-Disposition", "attachment", filename="image.jpg")
        msg.attach(img)

    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=15) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)
        return
    except smtplib.SMTPAuthenticationError:
        raise
    except Exception:
        pass
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
        server.ehlo()
        server.starttls(context=ctx)
        server.login(sender_email, sender_password)
        server.send_message(msg)


async def send_email(sender_email, sender_password, to_email, subject, content, photo_data=None):
    async with SMTP_SEM:
        try:
            await asyncio.to_thread(
                _smtp_send, sender_email, sender_password,
                to_email, subject, content, photo_data
            )
            return True
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"Auth error from {sender_email}: {e}")
            return "auth_error"
        except Exception as e:
            logger.error(f"Send error from {sender_email}: {e}")
            return False


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    user_id = update.effective_user.id

    if state == STATE_SET_EMAIL:
        text = update.message.text.strip() if update.message.text else ""
        if ":" not in text:
            await update.message.reply_text(
                "❌ صيغة خاطئة. يجب ارسالها بهذا الشكل:\n\nemail@gmail.com:كلمة المرور",
                reply_markup=back_keyboard(),
            )
            return

        parts = text.split(":", 1)
        email = parts[0].strip()
        password = parts[1].strip().replace(" ", "")

        if "@" not in email:
            await update.message.reply_text(
                "❌ بريد إلكتروني غير صحيح.", reply_markup=back_keyboard()
            )
            return

        user = get_user(user_id)
        existing = [e for e in user["emails"] if e["email"] == email]
        if existing:
            existing[0]["password"] = password
        else:
            user["emails"].append({"email": email, "password": password})
        save_user(user_id, user)
        context.user_data["state"] = STATE_IDLE
        await update.message.reply_text(
            f"✅ تم حفظ الايميل بنجاح:\n{email}",
            reply_markup=back_keyboard(),
        )

    elif state == STATE_SET_COUNT:
        text = update.message.text.strip() if update.message.text else ""
        if not text.isdigit():
            await update.message.reply_text(
                "❌ يجب إرسال رقم صحيح.", reply_markup=back_keyboard()
            )
            return

        count = int(text)
        user = get_user(user_id)
        total_max = MAX_DAILY * len(user["emails"])

        if count < 1:
            await update.message.reply_text(
                "❌ يجب إرسال رقم أكبر من 0.", reply_markup=back_keyboard()
            )
            return

        if count > total_max:
            await update.message.reply_text(
                f"❌ الحد الأقصى هو {total_max} بلاغ يومياً\n"
                f"({len(user['emails'])} ايميل × {MAX_DAILY} بلاغ لكل ايميل).",
                reply_markup=back_keyboard(),
            )
            return

        today = str(date.today())
        daily_sent = user.get("daily_sent", {})
        total_remaining = sum(
            MAX_DAILY - daily_sent.get(f"{em['email']}_{today}", 0)
            for em in user["emails"]
        )
        if total_remaining <= 0:
            await update.message.reply_text(
                              "❌ جميع الايميلات وصلت للحد اليومي، حاول غداً.",
                reply_markup=back_keyboard(),
            )
            return

        user["send_count"] = count
        save_user(user_id, user)
        context.user_data["state"] = STATE_IDLE
        await update.message.reply_text(
            f"✅ تم تعيين عدد الارسال: {count} بلاغ.",
            reply_markup=back_keyboard(),
        )

    elif state == STATE_SET_SUBJECT:
        subject = update.message.text.strip() if update.message.text else ""
        if not subject:
            await update.message.reply_text(
                "❌ الموضوع لا يمكن أن يكون فارغاً.", reply_markup=back_keyboard()
            )
            return
        user = get_user(user_id)
        user["subject"] = subject
        save_user(user_id, user)
        context.user_data["state"] = STATE_IDLE
        await update.message.reply_text(
            f"✅ تم تعيين الموضوع:\n{subject}",
            reply_markup=back_keyboard(),
        )

    elif state == STATE_SET_CONTENT:
        content = update.message.text.strip() if update.message.text else ""
        if not content:
            await update.message.reply_text(
                "❌ الكلايش لا يمكن أن يكون فارغاً.", reply_markup=back_keyboard()
            )
            return
        user = get_user(user_id)
        user["content"] = content
        save_user(user_id, user)
        context.user_data["state"] = STATE_IDLE
        await update.message.reply_text(
            "✅ تم تعيين الكلايش بنجاح.",
            reply_markup=back_keyboard(),
        )

    elif state == STATE_SET_SUPPORT:
        support = update.message.text.strip() if update.message.text else ""
        if "@" not in support:
            await update.message.reply_text(
                "❌ بريد إلكتروني غير صحيح.", reply_markup=back_keyboard()
            )
            return
        user = get_user(user_id)
        user["support"] = support
        save_user(user_id, user)
        context.user_data["state"] = STATE_IDLE
        await update.message.reply_text(
            f"✅ تم تعيين الدعم:\n{support}",
            reply_markup=back_keyboard(),
        )

    elif state == STATE_ADD_PHOTO:
        if update.message.photo:
            photo = update.message.photo[-1]
            user = get_user(user_id)
            user["photo"] = photo.file_id
            save_user(user_id, user)
            context.user_data["state"] = STATE_IDLE
            await update.message.reply_text(
                "✅ تم اضافة الصورة بنجاح.",
                reply_markup=back_keyboard(),
            )
        else:
            await update.message.reply_text(
                "❌ يجب ارسال صورة فقط.", reply_markup=back_keyboard()
            )


def main():
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"Flask server started on port {PORT}")

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, message_handler)
    )

    logger.info("Bot started successfully!")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
