 logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
  logger = logging.getLogger(__name__)

  TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')

  async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
      logger.info(f"--- MINIMAL BOT: /start received from user {update.effective_user.id} ---")
      try:
          await update.message.reply_text('Minimal bot on Render is responding to /start!')
          logger.info(f"--- MINIMAL BOT: Reply sent to user {update.effective_user.id} ---")
      except Exception as e:
          logger.error(f"--- MINIMAL BOT: Error sending reply: {e}", exc_info=True)

  async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
      """Log Errors caused by Updates."""
      logger.error("MINIMAL BOT: Exception while handling an update:", exc_info=context.error)

  async def post_init(application: Application) -> None:
      logger.info("MINIMAL BOT: Post-initialization tasks if any (e.g., set bot commands).")
      # await application.bot.set_my_commands([
      #     ("start", "Start the minimal bot")
      # ])


  if not TOKEN:
      logger.critical("CRITICAL MINIMAL BOT: TELEGRAM_BOT_TOKEN environment variable not set!")
  else:
      logger.info("Minimal bot starting with token...")
      application = Application.builder().token(TOKEN).post_init(post_init).build()
      application.add_handler(CommandHandler("start", start))
      application.add_error_handler(error_handler) # חשוב לראות שגיאות

      logger.info("Minimal bot starting polling...")
      # Using run_polling in a blocking way for this simple test script
      # When run directly with `python bot_minimal.py`
      # For Render, the start command will just be `python bot_minimal.py`
      # asyncio.run(application.run_polling()) # This line is if you run locally and want to block
      # For Render, we just need to start it and the script will keep running
      # The script ends if run_polling is not run in a blocking way or within an existing loop
      
      # Let's make sure polling runs indefinitely in a simple way for Render test
      loop = asyncio.get_event_loop()
      try:
          loop.run_until_complete(application.initialize())
          if application.updater: # updater is created by initialize if not present
              loop.run_until_complete(application.updater.start_polling())
          loop.run_until_complete(application.start())
          logger.info("Minimal bot is live and polling indefinitely (within script).")
          loop.run_forever() # Keep the loop running
      except (KeyboardInterrupt, SystemExit):
          logger.info("Minimal bot stopping polling...")
          if application.updater:
              loop.run_until_complete(application.updater.stop())
          loop.run_until_complete(application.stop())
          logger.info("Minimal bot stopped.")
      except Exception as e:
          logger.critical(f"Minimal bot CRASHED: {e}", exc_info=True)
      finally:
          if application.updater and application.updater.running: # Ensure it stops if loop.run_forever is interrupted
              loop.run_until_complete(application.updater.stop())
          if application.running:
              loop.run_until_complete(application.stop())
          loop.close()
          logger.info("Minimal bot asyncio loop closed.")

  # To run this script directly for Render (without Gunicorn):
  # The if __name__ == '__main__' block is not strictly needed if the file is run directly,
  # but good practice. The code above the `if TOKEN:` will run on import if not guarded.
  # However, for `python bot_minimal.py` as a start command, the top-level code will execute.
  ```
