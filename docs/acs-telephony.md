# ACS Telephony

VirtualRM accepts inbound phone calls through Azure Communication Services (ACS) while reusing the same Voice Live session, agents, SOPs, and CRM tools as the browser.

## Runtime Flow

1. A caller dials a phone number assigned to the ACS resource.
2. ACS publishes `Microsoft.Communication.IncomingCall` through Event Grid.
3. Event Grid calls `POST /api/acs/incoming-call`. The app validates the event resource, deduplicates its ID in Azure Table Storage, and calls `answer_call` using the Container App managed identity.
4. The answer request gives ACS two opaque-token URLs: an HTTPS callback and a WSS media endpoint.
5. Call Automation posts lifecycle events to the callback. Every request must contain an ACS-signed JWT whose audience is the ACS Azure resource ID.
6. ACS opens the media WebSocket with a separately signed JWT and call-correlation headers.
7. `AcsMediaTransport` unwraps base64 `AudioData` into PCM16 24-kHz mono bytes. `VoiceLiveSession` forwards those bytes to Voice Live without transcoding.
8. Voice Live performs VAD, transcription, inference, agent handoffs, CRM tool calls, and speech synthesis.
9. The transport wraps synthesized PCM bytes into ACS outbound `AudioData`. A Voice Live interruption event becomes ACS `StopAudio`.
10. Disconnect or failure callbacks remove call state. No audio is persisted.

Event Grid announces a new call; Call Automation answers and controls it; the media WebSocket carries audio. These are separate channels.

## Customer Verification

Caller ID is used only to find a possible CRM record. It does not authenticate a customer.

For the demo, the caller enters a four-digit telephone PIN using DTMF. The CRM dispatcher rejects every customer-data tool call until the PIN is verified. Demo PINs are seeded from the existing last-four values; a production deployment must replace this with the bank's existing OTP or IVR identity service.

Browser sessions retain their existing authenticated-demo behavior and are marked verified when opened.

## Identity and State

- The Container App user-assigned managed identity authenticates to ACS and Azure Table Storage.
- No ACS access key or Storage connection string is passed to the app.
- Callback and media JWTs validate the RS256 signature, ACS issuer, expiry, and ACS resource-ID audience.
- Azure Table Storage holds opaque call tokens, event IDs, correlation IDs, and expiry timestamps so multiple Container App replicas share state.
- Phone numbers, incoming-call contexts, JWTs, and raw PIN digits are not logged.

The target subscription currently exposes `Communication and Email Service Owner` as its narrowest ACS built-in role. It can list ACS keys even though this application never requests or stores them. Revisit the assignment when a narrower Call Automation role is available.

## Deployment Order

`azd provision` creates ACS, Table Storage, RBAC, and Container App configuration. `azd deploy` publishes the application. The post-deploy hook then deploys `acs-event-subscription.bicep`, because Event Grid validates the public webhook during subscription creation and the real route must already be live.

The phone number is acquired after deployment. Direct ACS number availability depends on subscription billing country, number country, number type, and regulatory eligibility. India is not currently offered for direct ACS number acquisition; an Indian number requires Direct Routing through a carrier and SBC.