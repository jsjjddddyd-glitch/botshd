import asyncio
import json
import os
import smtplib
import ssl
import logging
import threading
import time
async def send_email(sender_email, sender_password, to_email, subject, content, photo_data=None):
    async with SMTP_SEM:
        try:
            await asyncio.to_thread(
                _smtp_send, sender_email, sender_password,
                to_email, subject, content, photo_data
            )
            return True
        except Exception as e:
            logger.error(f"Send error from {sender_email}: {e}")
            return False


def _smtp_verify(email, password):
    ctx = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as server:
        server.ehlo()
        server.starttls(context=ctx)
        server.login(email, password)


async def verify_email(email, password):
    try:
        await asyncio.to_thread(_smtp_verify, email, password)
        return True, None
    except Exception as e:
        logger.error(f"Verify error: {e}")
        return False, str(e)


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

        wait_msg = await update.message.reply_text(
            "⏳ جاري التحقق من صحة الايميل وكلمة المرور..."
        )

        valid, err_msg = await verify_email(email, password)

        if valid:
            user = get_user(user_id)
            existing = [e for e in user["emails"] if e["email"] == email]
            if existing:
                existing[0]["password"] = password
            else:
                user["emails"].append({"email": email, "password": password})
            save_user(user_id, user)
            context.user_data["state"] = STATE_IDLE
            await wait_msg.edit_text(
                f"✅ تم تعيين الايميل بنجاح:\n{email}",
                reply_markup=back_keyboard(),
            )
        else:
            await wait_msg.edit_text(
                f"❌ الايميل أو كلمة المرور غير صحيحة.\n"
                f"تأكد من تفعيل كلمة مرور التطبيقات في إعدادات Gmail.\n\n"
                f"سبب الخطأ:\n{err_msg}",
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
