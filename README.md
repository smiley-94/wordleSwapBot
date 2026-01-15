# Wordle Swap Bot
=========================

This Telegram bot is for a whitelisted group to exchange **one photo per day** (Europe/Rome).\
When a user sends a Wordle screenshot, the bot automatically extracts the words using AI and adds a **clickable analyzer link** to the photo.

* * * * *

Features
--------

-   One photo per user per day

-   Whitelist-only access (admin managed)

-   Automatic Wordle word extraction:
    
    -   Bot automatically extracts words from your Wordle screenshot using AI
    -   Automatically fetches today's NYT Wordle solution and adds it to the analysis
    -   Generates a Wordle Analyzer link in Hard Mode for accurate analysis
    
-   Fan-out:

    -   Uploader receives earlier photos from today (with each photo's link and caption if present)
    -   If word extraction succeeds, uploader also gets their **own link** as a message
    -   Everyone who already uploaded today receives the new photo (+ link and caption if present)

-   Admin commands:

    -   `/resetToday <user_id|ALL>` - Delete today's image(s) for specific user or all users
    -   `/resetdb` - Wipe only images (preserves user whitelist)
    -   `/broadcast <message>` - Send silent messages to all allowed users

-   Internationalization through `lang.json` (EN/IT included)

-   Size caps for picked Telegram photo variant

-   Env-driven logging level

* * * * *

Caption Format
--------------

Add any text you want in the photo caption, it will be displayed as the third line to other users:



**Message format sent to users:**


[HH:mm] Full Name @username  
wordle analyzer link  
Custom text here (caption message)  

* * * * *

Commands
--------

**Everyone**

-   `/start` -- welcome

-   `/help` -- show user commands

-   `/id` -- show your Telegram user id

-   `/author` -- credits

**Admin**

-   `/allowed` -- list allowed users

-   `/allow <user_id>` -- allow a user

-   `/deny <user_id>` -- remove a user

-   `/resetdb` -- wipe only images (whitelist is preserved)

-   `/resetToday <user_id|ALL>` -- delete today's image(s) for user or all

-   `/broadcast <message>` -- send a silent message to all allowed users (supports HTML formatting)

> Non-allowed users get a localized message with their id to share with the admin.

**Broadcast Usage Example:**

/broadcast 🎉 New feature: You can now add custom messages in your captions!
/broadcast <b>Maintenance notice:</b> The bot will be offline tomorrow at 10:00 AM for 30 minutes.


* * * * *

Environment Variables
---------------------

All variables are **required**.

| Key                   | Description                                                   |
|-----------------------|---------------------------------------------------------------|
| `botToken`            | Telegram bot token                                            |
| `adminUserId`         | Admin Telegram user id (numeric)                              |
| `allowedUserArray`    | array of user ids that are allowed  (e.g. [132,321,12])       |
| `botMaxPhotoWidth`    | Max width for picked variant (e.g. `1280`)                    |
| `botMaxPhotoBytes`    | Max file size for picked variant (e.g. `1000000`)             |
| `botDbPath`           | SQLite database path (e.g. `/data/images.db`)                 |
| `botAnalyzerBase`     | Analyzer base URL                                             |
| `botAnalyzerLinkName` | Label shown for clickable link (e.g. `wordleAnalizer`)        |
| `logLevel`            | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`           |
| `ollamaApiKey`        | Ollama API key for authentication                             |
| `ollamaModelName`     | Model name for OCR processing (default: ministral-3:8b-cloud) |
| `ollamaHost`          | Ollama API endpoint (default: https://ollama.com)             |


Data Volume
---------------------
required for persistence of the data between restarts

| Path | Description                                |
|------|--------------------------------------------|
| `/data`  | Persistent storage for the SQLite database |
