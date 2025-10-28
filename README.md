Wordle Swap Bot
=========================

This Telegram bot is for a whitelisted group to exchange **one photo per day** (Europe/Rome).\
If a photo **caption** contains valid Wordle guesses, the bot adds a **clickable analyzer link** to the photo and sends it to participants.

* * * * *

Features
--------

-   One photo per user per day

-   Whitelist-only access (admin managed)

-   Wordle analyzer link from **photo captions only** generated when the **photo caption** is valid:

    -   Caption may contain **only letters and spaces**

    -   Each token must be a **5-letter** word

    -   One or more words (max seven); **last word = solution**

    -   uppercase if you play in **Hard Mode**
    
    -   Link appears as a **clickable label**
    
-   Fan-out:

    -   Uploader receives earlier photos from today (with each photo's link if present)

    -   If uploader's caption is valid, they also get their **own link** as a message

    -   Everyone who already uploaded today receives the new photo (+ link if present)

-   Internationalization through `lang.json` (EN/IT included)

-   Size caps for picked Telegram photo variant

-   Env-driven logging level

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

-   `/resetdb` -- wipe the images table (whitelist is kept)

> Non-allowed users get a localized message with their id to share with the admin.

* * * * *

All variables are **required**.

| Key | Description                                             |
| --- |---------------------------------------------------------|
| `botToken` | Telegram bot token                                      |
| `adminUserId` | Admin Telegram user id (numeric)                        |
| `allowedUserArray` | array of user ids that are allowed  (e.g. [132,321,12]) |
| `botMaxPhotoWidth` | Max width for picked variant (e.g. `1280`)              |
| `botMaxPhotoBytes` | Max file size for picked variant (e.g. `1000000`)       |
| `botDbPath` | SQLite database path (e.g. `/data/images.db`)           |
| `botAnalyzerBase` | Analyzer base URL                                       |
| `botAnalyzerLinkName` | Label shown for clickable link (e.g. `wordleAnalizer`)  |
| `logLevel` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`     |