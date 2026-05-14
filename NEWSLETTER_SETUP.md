# Newsletter Ingestion - Gmail Setup

The platform can monitor a dedicated Gmail inbox for partner/investor
newsletters and pull each one in as a content item, tagged to the
relevant company. This guide is the layman version: do these steps in
order and it works.

## What you need

- A new (or existing) Gmail account you are willing to dedicate to
  newsletters. Do **not** use a personal inbox - this account exists
  only to receive newsletters the team subscribes to.
- About 10 minutes.

If you already have an existing setup and just need to give the team your
credentials, skip to **Step 5**.

## Step 1: Create the inbox

Make a new Gmail account at https://accounts.google.com. Suggested name:
something like `forge.newsletters@gmail.com` or
`mcmaster.startup.intel@gmail.com`. Whatever you pick, write the address
down - the team will need it.

If you would rather use an existing inbox, you can - but the platform will
read every email in there.

## Step 2: Turn on IMAP

1. Open Gmail with the new account.
2. Click the gear icon (top right) -> **See all settings**.
3. Go to the **Forwarding and POP/IMAP** tab.
4. Under "IMAP access", click **Enable IMAP**.
5. Click **Save Changes** at the bottom.

## Step 3: Turn on 2-Step Verification

You cannot generate an App Password without this. It is free.

1. Go to https://myaccount.google.com/security.
2. Find "How you sign in to Google" -> click **2-Step Verification**.
3. Follow Google's prompts. You will need a phone for the verification code.

## Step 4: Create an App Password

This is the password the platform will use - it is **not** your normal
Gmail password.

1. Go to https://myaccount.google.com/apppasswords.

   (If that page says "the setting is not available for your account", it
   means 2-Step Verification did not finish setting up. Go back to Step 3.)

2. App name (free text): `Startup Intel`.
3. Click **Create**.
4. Google shows a 16-character password like `abcd efgh ijkl mnop`.
   **Copy it now** - you cannot see it again later.
5. Remove the spaces. The actual password you save is `abcdefghijklmnop`.

## Step 5: Give the credentials to the developer

Send the developer these three pieces of information **securely** (1Password,
Bitwarden, encrypted note, in person - not plain email or Slack DM):

```
Gmail address:        forge.newsletters@gmail.com
App password:         abcdefghijklmnop
IMAP host:            imap.gmail.com   (always this)
```

The developer will set them on Fly.io with:

```
flyctl secrets set NEWSLETTER_EMAIL=forge.newsletters@gmail.com
flyctl secrets set NEWSLETTER_APP_PASSWORD=abcdefghijklmnop
flyctl secrets set NEWSLETTER_IMAP_HOST=imap.gmail.com
flyctl deploy
```

## Step 6: Subscribe the inbox to newsletters

Now use the new Gmail address to subscribe to the newsletters you actually
want ingested:

- Partner companies' "what's new" mailing lists
- Investor portfolio updates
- Incubator and accelerator program updates

Avoid generic tech newsletters - they will swamp the dashboard with
unmatched content.

You can also **forward** existing newsletters you receive in your personal
inbox to this address. The platform treats forwarded mail the same way.

## Step 7: Verify

After the developer has deployed:

1. Send a test email to the new Gmail address (from anywhere - even your
   personal inbox).
2. On the dashboard, click **Run Ingestion** -> **Ingest Next Batch**.
   (Or wait for the next scheduled run.)
3. The test email should appear in the dashboard feed under the matching
   company, or under "Unmatched Items" if the email did not mention any
   known company.

If nothing appears: the developer should check `flyctl logs` and look for
lines starting with `[Newsletter]`.

## Frequently asked questions

### "Will the platform send email from this inbox?"

No. It only reads.

### "What if I lose the App Password?"

You can generate a new one (Step 4 again). Old App Passwords keep working
until you revoke them.

### "Does the platform delete or move emails?"

No. It reads them with IMAP, marks them as "processed" internally (in its
own database), and leaves the inbox untouched.

### "What if I want to stop monitoring an inbox?"

Tell the developer to run `flyctl secrets unset NEWSLETTER_EMAIL
NEWSLETTER_APP_PASSWORD` and redeploy.

### "Can I use Outlook / Yahoo / a custom domain?"

Technically yes - any IMAP server works. Set `NEWSLETTER_IMAP_HOST` to the
right server (e.g. `outlook.office365.com`). Gmail is the path we have
tested.
