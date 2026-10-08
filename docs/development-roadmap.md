# Current development roadmap

The owner's latest sequence prioritizes a usable private multiplayer build. This order follows the verified `OWNERSHIP_FOUNDATION_POC`; the full [master specification](master-spec.md) remains accepted scope. The [combined amendment](project-update-customization-friendship-shiny-charm.txt) is preserved byte-for-byte, including customization, reuse research, player friendship/Lucky trading, and the Shiny Charm/Game Corner reward. Adding these requirements does not mark them implemented.

## Immediate order

| Order | Work | Completion evidence |
| --- | --- | --- |
| 1 | Safe player-to-player trading | Offers and explicit mutual confirmation; edits invalidate consent; both canonical saves and ownership changes commit together; cancellation, retry, disconnect, server restart, and fresh Continue neither duplicate nor lose Pokémon. Preserve ordinary Pokémon attributes. Exercise actual ROMs before claiming playable trading. |
| 2 | Multiplayer battles and team features | Conventional 1v1 and 2v2; independent parties/rewards; invite, accept, leave, and change two-player teams; two teams may coexist. Verify battle synchronization and interruption recovery. Championship, currency wagers, and custom 1v1v1v1 retain their specified designs and separate acceptance gates. |
| 3 | Four-player testing | Four actual game clients, independent maps/encounters/saves, simultaneous teams, trading and 1v1/2v2, join/leave/rejoin, capacity limits, and host restart. Synthetic clients supplement this proof. |
| 4 | Local encounter Soft Reset | Build the necessary personal/static encounter and independent RNG/shiny hooks; reset only an eligible local hunt while three other players continue unaffected. Preserve ownership, counters, and committed captures; exclude wild/event rerolls. Test cancellation and interruptions. |
| 5 | Automatic saving and disconnect handling | Safe-point scheduling, visible pending/recovery status, reconnect policy, interrupted interaction recovery, and migration/backup checks. Define outstanding offline and battle policies before enabling them. Earlier trade/battle milestones already require transaction-specific crash safety; this step completes the player-facing lifecycle. |
| 6 | Downloadable Windows Host Game / Join Game | Bundled runtime and usable launcher, isolated profiles, reviewed dependencies/assets and import/patch flow, clean-machine installation, hosting/joining, error messages, and updates. Friends need no compiler, Python, WSL, or manual Lua setup. |
| 7 | Wi-Fi/Internet testing and polish | Actual separate PCs, LAN/Wi-Fi and port-forwarded Internet, firewall/connection setup, latency/loss/reconnect, compatible builds, transport security, performance, and clear recovery. Test earlier locally as needed; this is the delivery acceptance gate. |

The sequence does not turn basic test builds into the completed game. Report actual supported features at each release. Hoenn remains first, with one to four total players including the host.

## Added feature placement

| Addition | Placement and boundaries |
| --- | --- |
| Trainer customization | Research and define the synchronized appearance contract now. Implement the creator and remote rendering after core multiplayer/four-client proof; complete before claiming the customization feature delivered. In the finished game, creation happens near the beginning, with later changes and optional cosmetic unlocks. Advanced Trainer Card work follows. |
| Player friendship and Lucky trades | Reserve compatible transaction/history hooks during safe trade design. Implement after ordinary trades are proven: pair persistence and meaningful progression, Lucky conversion and presentation, Best Friends/Lucky Friends, then Friends UI. It does not jump ahead of the owner's immediate multiplayer sequence or gate basic trades/teams. |
| Personal Shiny Charm | Establish encounter-source and personal-modifier boundaries alongside Local Soft Reset. Implement after Gen 6 shiny rules, personal encounter independence, and saves are verified. Research exact odds before enabling effects. |
| Game Corner reward | Later acquisition/content work: existing minigames, coins, and redemption components first; guaranteed purchase at a meaningful, later-balanced coin price. Multiplayer casino activities are optional. |
| Research and reuse | Applies before every major system, starting now. Check existing engine capabilities and current compatible projects, then record why integration/adaptation or custom work is selected. Never import a whole gameplay redesign just to reuse one component. |

Gen 1–6 roster restrictions, complete Gen 6 mechanics, 18 starters, eligible official Megas, randomized encounters/rarity, shinies, followers, Twin Gyms, events, Championship/wagers, custom four-way battles, and eventual additional regions remain on the full content backlog. Omission from the immediate seven-step list does not cancel them. Pull forward only the dependencies required for the selected milestone, and label partial coverage honestly.

## Decisions intentionally pending

No numerical friendship thresholds, Lucky odds or IV floor, Lucky eligibility/cooldowns, casino coin price, or final Charm odds are selected by this planning update. Secondary Lucky benefits, repeated Lucky conversion, the treatment of both sides of a Lucky trade, and IV changes that affect Hidden Power's type also require design/balance work. No existing gameplay rule may be changed for compatibility without first explaining the concrete conflict and obtaining the owner's decision.

Read the [reuse and customization audit](customization-and-reuse.md) before implementing the new features. Preserve the existing source/build pins and save profiles until a tested migration is ready.
