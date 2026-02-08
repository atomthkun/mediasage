# Getting a Free Gemini API Key for MediaSage

MediaSage uses an AI model to curate playlists from your Plex music library. It needs an API key to talk to that model. Google's Gemini API has a **free tier** that works well for personal playlist generation — here's how to set it up and what to expect.

---

## Step 1: Get Your Free API Key

1. Go to [aistudio.google.com](https://aistudio.google.com) and sign in with any Google account
2. Click **"Get API key"** in the top navigation (or go directly to [aistudio.google.com/apikey](https://aistudio.google.com/apikey))
3. Click **"Create API key"** and select or create a Google Cloud project when prompted
4. Copy the key — you'll need it for your MediaSage config

No credit card is required. No billing setup. You're immediately on the free tier.

## Step 2: Add the Key to MediaSage

In your `docker-compose.yml` (or however you've configured MediaSage), set your Gemini API key as an environment variable and configure the LLM provider. For example:

```yaml
services:
  mediasage:
    image: ghcr.io/ecwilsonaz/mediasage:latest
    environment:
      - GEMINI_API_KEY=your-api-key-here
```

Refer to MediaSage's configuration docs for the exact environment variable names and model settings for your version.

## Step 3: Start Generating Playlists

That's it. Fire up MediaSage, type a prompt like *"mellow 90s indie for a rainy afternoon"*, and the AI will curate a playlist from your actual Plex library.

---

## What Does the Free Tier Get Me?

### Models available for free

| Model | Speed | Quality | Free? |
|---|---|---|---|
| **Gemini 2.5 Flash** | Fast | Great for playlists | ✅ Yes |
| Gemini 2.5 Flash-Lite | Fastest | Good, cheaper | ✅ Yes |
| Gemini 2.5 Pro | Slower | Best quality | ✅ Yes (low limits) |
| Gemini 3 Flash Preview | Fast | Newest | ✅ Yes |
| Gemini 3 Pro Preview | Slower | Most capable | ❌ Paid only |

**Gemini 2.5 Flash** is the sweet spot for MediaSage — it's fast, handles the track list context well, and has the most generous free rate limits.

### Rate limits (approximate, as of Feb 2026)

| Model | Requests/Minute | Requests/Day |
|---|---|---|
| Gemini 2.5 Flash | ~10-15 | ~100-500 |
| Gemini 2.5 Pro | ~5 | ~25-50 |
| Gemini 3 Flash Preview | ~10-15 | ~500-1,000 |

For personal use, this is plenty. Even at the low end of 100 requests/day, that's 100 playlists — far more than you'd realistically generate. Rate limits reset at midnight Pacific Time.

> **Note:** Google reduced free tier quotas significantly in December 2025. If you hit rate limits, you're probably fine waiting a bit and trying again.

### Context window

All Gemini models support a **1 million token context window**. MediaSage sends a sample of your library (~500-650 tracks) to the AI, which is well within this limit even for very large libraries. Context window is not a constraint.

---

## How Much Does Each Playlist Cost?

On the free tier: **$0.00**.

If you ever move to the paid tier, here's what a typical MediaSage playlist generation costs with Gemini 2.5 Flash:

- MediaSage sends ~650 tracks to the AI (~15-20K input tokens depending on metadata)
- The AI returns a 25-track playlist as JSON (~500-1K output tokens)
- **Estimated cost per playlist: ~$0.01-0.03**

Even on paid, this is extremely cheap. But for personal use, the free tier should be all you need.

---

## Important Things to Know

### Your data on the free tier

On the free tier, Google may use your prompts and responses to improve their products. In practice, this means your track lists and playlist prompts could be used for model training. For a self-hosted playlist generator pulling from your personal music library, this is low-risk — but worth knowing.

If this concerns you, enabling billing (even with $0 spent) upgrades you to the paid tier where your data is **not** used to improve Google's products.

### Regional restrictions

The free tier may not work if you're accessing it from EU, UK, or Switzerland. If you're in one of these regions, you may need to set up billing (see the "$300 free credits" option below).

### Rate limit errors

If you see 429 errors, you've hit your rate limit. Wait a minute and try again, or wait until the daily reset at midnight PT. MediaSage should handle this gracefully, but if you're generating a lot of playlists in a short period, this is the likely cause.

---

## Want More? Additional Free Options

### $300 Google Cloud credits (new users)

If you've never had a Google Cloud billing account, you can get **$300 in free credits** valid for 90 days:

1. In [Google AI Studio](https://aistudio.google.com), go to **Settings → Plan information**
2. Click **"Set up Billing"** and create a new billing account
3. A credit card is required, but you won't be charged until the $300 runs out
4. This also upgrades you to the paid tier (higher rate limits, data not used for training)

At ~$0.02 per playlist, $300 would cover roughly **15,000 playlists** — effectively unlimited for personal use, plus you get the privacy benefits of the paid tier.

### Google AI Pro subscriber credits

If you already pay for Google AI Pro ($19.99/month), you get **$10/month in Google Cloud credits** that can be applied to Gemini API usage. Activate this through the [Google Developer Program](https://developers.google.com/profile). That $10 covers hundreds of playlists per month.

### Google AI Studio (for testing prompts)

If you want to experiment with how different prompts affect playlist quality before running them through MediaSage, [Google AI Studio](https://aistudio.google.com) lets you interact with Gemini models directly in the browser for free. It doesn't count against your API rate limits.

---

## Quick Reference

| What | Details |
|---|---|
| Get your key | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| Cost | Free (no credit card needed) |
| Recommended model | Gemini 2.5 Flash |
| Playlists per day (free) | ~100-500 |
| Context window | 1M tokens (more than enough) |
| Data privacy (free tier) | Prompts may be used by Google |
| Data privacy (paid tier) | Prompts not used by Google |

---

*Last updated: February 8, 2026. Check [ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing) for the latest rate limits and pricing.*
