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

    -   Caption may contain **only letters, spaces, and @ symbol**
    
    -   Words **before** the `@` symbol are parsed as Wordle guesses
    
    -   Each token must be a **5-letter** word
    
    -   One or more words (max seven); **last word = solution**
    
    -   Uppercase if you play in **Hard Mode**
    
    -   Text **after** the `@` symbol is sent as **custom message** (third line) to other users
    
    -   Link appears as a **clickable label**
    
-   Fan-out:

    -   Uploader receives earlier photos from today (with each photo's link and custom text if present)
    
    -   If uploader's caption is valid, they also get their **own link** as a message
    
    -   Everyone who already uploaded today receives the new photo (+ link and custom text if present)

-   Admin broadcast: send silent messages to all allowed users

-   Internationalization through `lang.json` (EN/IT included)

-   Size caps for picked Telegram photo variant

-   Env-driven logging level

* * * * *

Caption Format
--------------

**Example captions:**

- `BREAD STEAM BEACH PEACE` - Valid Wordle in Hard Mode (uppercase)
- `bread steam beach peace` - Valid Wordle in Normal Mode (lowercase)
- `bread steam beach peace @ Great game today!` - Wordle + custom message
- `CRANE CRATE TRADE @ Difficult one!` - Hard Mode + custom message

**Message format sent to users:**


[HH:mm] Full Name @username  
wordle analyzer link  
Custom text here (if provided after @)  

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

-   `/broadcast <message>` -- send a silent message to all allowed users (supports HTML formatting)

> Non-allowed users get a localized message with their id to share with the admin.

**Broadcast Usage Example:**

/broadcast 🎉 New feature: You can now add custom messages after @ in your captions!
/broadcast <b>Maintenance notice:</b> The bot will be offline tomorrow at 10:00 AM for 30 minutes.


* * * * *

Environment Variables
---------------------

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
