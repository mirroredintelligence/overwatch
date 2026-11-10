# Sign-in stings: provenance

Three short voice stings, played after sign-in when a person has turned the sound on (not built yet; see "Playing them"). The audio is in `frontend/public/sounds/`. This file is kept out of `public/` so it is not served.

| Clip | MP3 (default source) | OGG/Opus (fallback source) | Length |
|---|---|---|---|
| "AQIKO online" | `aqiko-online.mp3`, 11,327 bytes, sha256 `c9e38e80ad4bd117f92b9ba45a65428a122aa7ae3143daba59299845573e4e73` | `aqiko-online.ogg`, 5,911 bytes, sha256 `f90970c396662d69d3663a9eae29361cfa152dd167b5aaaf2e325e1ef4cd9acc` | about 1.3 s |
| "AQIKO standing by" | `aqiko-standing-by.mp3`, 12,163 bytes, sha256 `7f0575bb09d3b613d704aaefa4356377683abce560ebc02e946d12612a8b4a6e` | `aqiko-standing-by.ogg`, 6,376 bytes, sha256 `791b0ee3e77cc819f02a0547d85fa66c838023e33a755f05fbfcc2ddeb173d44` | about 1.4 s |
| "AQIKO ready" | `aqiko-ready.mp3`, 8,611 bytes, sha256 `16d33a2886f3dcd6e78aeb114d612c9ab03666c93d5219f4bd7b1fca890469be` | `aqiko-ready.ogg`, 4,453 bytes, sha256 `a94283d7b9131675b29fc2e2a16346fa8125ec45f140e4815de5107650641b41` | about 1.0 s |

Lengths are as reported by the marketing-agents session; the byte counts and hashes were checked against the files on disk when they were copied (2026-11-10).

## Where they came from

- Rendered in the marketing-agents repo, `build/aqiko-voice/` (gitignored there; `raw/` holds the 24 kHz mono WAV originals, `mp3/` and `ogg/` the encodings, with the "ah" and respelled pronunciation candidates). The files here are the "b" pronunciation set, renamed without the suffix.
- Voice: Azure AI Speech, `en-GB-Ollie:DragonHDLatestNeural`, the same house voice as the reels. SSML: `<phoneme alphabet="ipa" ph="əˈkiːkəʊ">AQIKO</phoneme>` followed by the words (online, standing by, ready). The product owner chose pronunciation b (uh-KEE-koh) and these three wordings by listening.
- Encoding: silence trimmed, loudness about -18 LUFS, 15 ms fade in and 30 ms fade out; MP3 44.1 kHz mono 64 kbps, Opus 48 kHz mono 32 kbps. Both measured about -18 dB mean with a peak near -5 dB.
- Cost: about 129 characters of synthesis in total.

## Open before release

- **Licence is unconfirmed.** The marketing session found only secondhand Microsoft Q&A answers (paid-tier prebuilt neural output may be used commercially, with conditions). Read Microsoft's Product Terms and the Azure Speech transparency note directly. The Dragon HD offering was said to have changed in March 2026: check the current terms for it.
- **Disclosure.** Add a short "synthetic voice" note on the app's about page.
- **Nobody in the build sessions has heard the files.** The owner chose them by listening; the sessions could not play audio.

## Playing them

Browsers block sound that starts without a person having interacted with the site. The sign-in goes through an identity-provider redirect, so the page that plays the sting has no click of its own. The approach (attempt on arrival, fall back to the first click or key press, off by default, always a visible mute control, never the same clip twice in a row) is described in the conversation that added these files and is to be specified as its own unit; nothing in the app plays them yet.
