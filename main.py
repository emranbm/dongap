"""Telegram bot for group expense splitting."""

import os
import logging
from dotenv import load_dotenv
from telegram import Update, Chat
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

from db import Database
from expense_calculator import ExpenseCalculator

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Initialize database
Database.init_db()

# Conversation states
EXPENSE_AMOUNT, EXPENSE_DESC, EXPENSE_MEMBER = range(3)


# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    if update.message.chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
        user = update.message.from_user
        group_id = update.message.chat.id
        group_name = update.message.chat.title

        # Create group in database
        Database.create_group(group_id, group_name)

        # Add user as admin if they started the bot
        Database.add_member(
            group_id,
            user.id,
            user.username or user.first_name,
            user.first_name,
            is_admin=True,
        )

        await update.message.reply_text(
            "👋 Welcome to Dongap! 🎉\n\n"
            "I can help you track group expenses and calculate fair splits.\n\n"
            "Use /help to see available commands.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "👋 Welcome to Dongap! 🎉\n\n"
            "Add me to a group to start tracking expenses.\n\n"
            "Use /help to see available commands.",
            parse_mode="Markdown",
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    help_text = """
    📚 *Available Commands*
    
    /add_expense <amount> <description> - Add an expense (you paid)
    /summary - Show expense summary
    /settle - Calculate settlements
    /members - List group members
    /clear - Clear all expenses (admin only)
    /leave - Leave the group
    
    *Examples:*
    `/add_expense 500 Dinner for all`
    `/add_expense 1000 Movie tickets`
    """
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle when bot is added or removed from a group."""
    result = update.my_chat_member
    
    if result.new_chat_member.status == "member":
        # Bot was added to group
        group_id = result.chat.id
        group_name = result.chat.title
        
        Database.create_group(group_id, group_name)
        logger.info(f"Bot added to group {group_name} ({group_id})")
        
    elif result.new_chat_member.status == "left" or result.new_chat_member.status == "kicked":
        # Bot was removed from group
        logger.info(f"Bot removed from group {result.chat.id}")


async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /add_expense command."""
    if update.message.chat.type not in [Chat.GROUP, Chat.SUPERGROUP]:
        await update.message.reply_text(
            "This command only works in groups. Add me to a group first!"
        )
        return

    group_id = update.message.chat.id
    user = update.message.from_user

    # Ensure member is in database
    Database.add_member(
        group_id,
        user.id,
        user.username or user.first_name,
        user.first_name,
    )

    # Parse command arguments
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /add_expense <amount> <description>\n"
            "Example: /add_expense 500 Dinner for all",
            parse_mode="Markdown",
        )
        return

    try:
        amount = float(args[0])
        description = " ".join(args[1:])

        if amount <= 0:
            await update.message.reply_text("Amount must be positive!")
            return

        # Add expense to database
        Database.add_expense(
            group_id,
            user.id,
            user.first_name,
            amount,
            description,
        )

        await update.message.reply_text(
            f"✅ Expense added!\n\n"
            f"{user.first_name} paid ₹{amount:.2f} for: {description}",
            parse_mode="Markdown",
        )

    except ValueError:
        await update.message.reply_text(
            "Invalid amount! Please use a valid number.\n"
            "Example: /add_expense 500 Dinner"
        )


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /summary command."""
    if update.message.chat.type not in [Chat.GROUP, Chat.SUPERGROUP]:
        await update.message.reply_text("This command only works in groups!")
        return

    group_id = update.message.chat.id
    expenses = Database.get_expenses(group_id)
    members = Database.get_members(group_id)

    if not expenses:
        await update.message.reply_text("No expenses recorded yet! Use /add_expense to add one.")
        return

    summary_text = ExpenseCalculator.format_summary(
        ExpenseCalculator.calculate_summary(expenses, members)
    )
    await update.message.reply_text(summary_text, parse_mode="Markdown")


async def settle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settle command."""
    if update.message.chat.type not in [Chat.GROUP, Chat.SUPERGROUP]:
        await update.message.reply_text("This command only works in groups!")
        return

    group_id = update.message.chat.id
    expenses = Database.get_expenses(group_id)
    members = Database.get_members(group_id)

    if not expenses:
        await update.message.reply_text("No expenses to settle!")
        return

    settlements = ExpenseCalculator.calculate_settlements(expenses, members)
    settlements_text = ExpenseCalculator.format_settlements(settlements)
    
    await update.message.reply_text(settlements_text, parse_mode="Markdown")


async def members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /members command."""
    if update.message.chat.type not in [Chat.GROUP, Chat.SUPERGROUP]:
        await update.message.reply_text("This command only works in groups!")
        return

    group_id = update.message.chat.id
    group_members = Database.get_members(group_id)

    if not group_members:
        await update.message.reply_text("No members in this group yet!")
        return

    lines = ["👥 *Group Members*\n"]
    for i, member in enumerate(group_members, 1):
        admin_badge = "👨‍💼" if member.is_admin else "👤"
        lines.append(f"{admin_badge} {i}. {member.first_name}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def clear_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clear command."""
    if update.message.chat.type not in [Chat.GROUP, Chat.SUPERGROUP]:
        await update.message.reply_text("This command only works in groups!")
        return

    group_id = update.message.chat.id
    user = update.message.from_user
    members = Database.get_members(group_id)

    # Check if user is admin
    user_member = next((m for m in members if m.user_id == user.id), None)
    if not user_member or not user_member.is_admin:
        await update.message.reply_text(
            "❌ Only admin can clear expenses!"
        )
        return

    Database.clear_expenses(group_id)
    await update.message.reply_text(
        "🗑️ All expenses cleared!",
        parse_mode="Markdown",
    )


async def leave_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /leave command."""
    if update.message.chat.type not in [Chat.GROUP, Chat.SUPERGROUP]:
        await update.message.reply_text("This command only works in groups!")
        return

    group_id = update.message.chat.id
    user = update.message.from_user

    Database.remove_member(group_id, user.id)
    await update.message.reply_text(
        f"👋 {user.first_name} left the group!",
    )


async def track_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Track members joining the group."""
    if update.message.chat.type not in [Chat.GROUP, Chat.SUPERGROUP]:
        return

    group_id = update.message.chat.id
    user = update.message.from_user

    # Add or update member
    Database.add_member(
        group_id,
        user.id,
        user.username or user.first_name,
        user.first_name,
    )


def main() -> None:
    """Start the bot."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env file")

    # Create application
    application = Application.builder().token(token).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add_expense", add_expense))
    application.add_handler(CommandHandler("summary", summary))
    application.add_handler(CommandHandler("settle", settle))
    application.add_handler(CommandHandler("members", members))
    application.add_handler(CommandHandler("clear", clear_expenses))
    application.add_handler(CommandHandler("leave", leave_group))

    # Track members
    application.add_handler(MessageHandler(filters.ALL, track_member))

    # Handle bot added/removed
    application.add_handler(MessageHandler(filters.StatusUpdate.CHAT_MEMBER, my_chat_member))

    # Start the bot
    logger.info("Bot started!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
