# Feishu Console Setup on Windows

This document separates what the local code and tests already cover from the manual work that still must be completed in the Feishu/Lark developer console.

## Already Completed Locally

- Backend webhook route exists at:
  - `/api/feishu/webhook`
- Local URL verification challenge is handled.
- Verification token validation is handled.
- Invalid JSON returns `400`.
- Wrong verification token returns `401`.
- `im.message.receive_v1` text message events are parsed.
- Non-text messages receive a safe reply.
- Text messages are passed to `AgentService`.
- Feishu reply calls can be mocked in local tests.
- Duplicate `event_id` or `message_id` events are deduped.
- Webhook processing can acknowledge quickly and run agent work through `BackgroundTasks`.
- Background task exceptions are logged without printing full sensitive message content.

## Manual Steps in Feishu Open Platform

1. Create an enterprise self-built application.

2. Enable the bot capability for the application.

3. Get the App ID and App Secret from the Feishu console.
   Store them only in the local `.env` file:
   - `FEISHU_APP_ID`
   - `FEISHU_APP_SECRET`

4. Configure a verification token in the Feishu console.
   Store the same token only in the local `.env` file:
   - `FEISHU_VERIFICATION_TOKEN`

5. For initial local integration, use plaintext event delivery.
   The current code rejects encrypted events with a clear `400` response. Do not enable encrypted event delivery until encryption support is implemented and verified.

6. Prepare an HTTPS public callback URL.
   The final callback path must be:
   - `/api/feishu/webhook`

   Example shape:
   - `https://<public-host>/api/feishu/webhook`

7. Fill the HTTPS callback URL into the Feishu event subscription callback field.
   If the exact current console menu name differs, confirm it in the current Feishu console UI rather than guessing.

8. Subscribe to:
   - `im.message.receive_v1`

9. Apply for the bot permissions required to read incoming messages and reply to messages.
   The exact permission names can change in the Feishu console; confirm the current names in the console before publishing. Look for permissions related to:
   - Receiving message events.
   - Reading message content sent to the bot.
   - Sending or replying to messages as the bot.

10. Publish a new app version after permissions and event subscriptions are configured.

11. Add the bot to a test group chat, or allow direct chat if your organization policy supports it.

12. Send a real test text message to the bot.
   Do not use real production-sensitive content for the first test.

13. Check backend logs:
   - `data\logs\backend.stdout.log`
   - `data\logs\backend.stderr.log`

   Confirm:
   - event ID was received.
   - duplicate events are ignored.
   - the agent was called once for the message.
   - reply status was recorded.

## Local Preflight

Run:

```powershell
.\scripts\windows\feishu_preflight.ps1
```

The script prints boolean configuration status only. It must not print secrets, access tokens, or the full `.env` contents.

If `FEISHU_APP_ID` or `FEISHU_APP_SECRET` is missing, tenant token testing is skipped and the script prints:

```text
飞书 live preflight：缺少凭证，未执行 tenant_access_token 测试。
```

## Public Tunnel Note

For local Feishu event subscriptions, the callback must be reachable from the public internet through HTTPS. If neither `cloudflared` nor `ngrok` is available locally, the callback cannot be reached by Feishu until a public HTTPS tunnel or deployment URL is provided.
