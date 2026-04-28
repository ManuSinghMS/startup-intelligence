# 📧 Newsletter Ingestion — Gmail Setup Guide

This guide walks through setting up the Gmail account that will receive partner/investor newsletters for automatic ingestion into the Startup Intel platform.

> **Important:** The newsletters we want are from **partners/investors**, NOT general tech newsletters.

## Step 1: Create a Dedicated Gmail Account

1. Go to [accounts.google.com](https://accounts.google.com) → **Create account**
2. Create something like `forge.newsletters@gmail.com`
3. Complete the signup process

## Step 2: Enable IMAP Access

1. Open Gmail with the new account
2. Go to **Settings** (gear icon) → **See all settings**
3. Click the **Forwarding and POP/IMAP** tab
4. Under **IMAP access**, select **Enable IMAP**
5. Click **Save Changes**

## Step 3: Enable 2-Factor Authentication (Required for App Passwords)

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Under **Signing in to Google**, click **2-Step Verification**
3. Follow the prompts to enable 2FA (you'll need a phone number)
4. Complete the verification

## Step 4: Create an App Password

1. After enabling 2FA, go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. Under **Select app**, choose **Mail**
3. Under **Select device**, choose **Other** → type `Startup Intel`
4. Click **Generate**
5. Google will show a 16-character password like `abcd efgh ijkl mnop`
6. **Copy this password** — you'll need it in the next step

## Step 5: Configure the Platform

Open the `.env` file in the project root and fill in:

```
NEWSLETTER_EMAIL=forge.newsletters@gmail.com
NEWSLETTER_APP_PASSWORD=abcdefghijklmnop
NEWSLETTER_IMAP_HOST=imap.gmail.com
```

> **Note:** Remove spaces from the App Password. If Google gave you `abcd efgh ijkl mnop`, enter it as `abcdefghijklmnop`.

## Step 6: Subscribe to Newsletters

Using the new Gmail account (`forge.newsletters@gmail.com`), subscribe to partner/investor newsletters. For example:
- Partner company update emails
- Investor portfolio update newsletters
- Incubator/accelerator program newsletters

The system will automatically:
1. Connect to the Gmail inbox on each ingestion cycle (every 60 minutes by default)
2. Read unprocessed emails
3. Extract the content
4. Match it to known companies in the database
5. Store it as `newsletter` source type

## Step 7: Verify It Works

After setting up the `.env` variables and restarting the server:
1. Send a test email to the new Gmail address
2. Click **🔄 Run Ingestion** on the dashboard
3. The newsletter content should appear in the feed

## Notes for Lauren

- **Only subscribe to partner/investor newsletters** with this email — not general tech newsletters
- The system matches emails to companies by checking if the company name appears in the email sender, subject, or body
- If a newsletter doesn't get matched to a company, it will still be stored under "Unmatched Items"
- You can forward existing newsletter emails to this address too — the system will pick them up
