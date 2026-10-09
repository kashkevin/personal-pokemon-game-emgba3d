"""Actual Windows paired native trade commit followed by host-service loss.

Both copied genuine characters explicitly approve their real native candidates.
A read-only watcher observes the durable paired commit and closes the actual
host service. The cut qualifies only if both original games retain their trade
journals and neither recipient has acknowledged. Production host restart and
independent observer leases verify the exact committed candidates without any
release, renewal, save or replacement of those originals. After normal closure,
fresh Host/Join performs strict canonical recovery, both ACKs, received-result
summaries, Continue and manual saving. Every game must close normally.

No methods, outcomes or receipts are injected. A cut that misses the original
holds fails rather than claiming committed recovery. This is a same-machine
service-loss case with non-evolving genuine parties; it does not qualify whole
app/PC failure, evolution choices, physical inputs or Internet play.
"""
import asyncio
from functools import partial

from qualify_menu_trade_effects import arguments, run
from qualify_trade_service_loss import interrupted_trade


if __name__ == "__main__":
    asyncio.run(run(arguments(__doc__), trade_flow=partial(interrupted_trade, committed=True),
                    interrupted=True, interrupted_outcome="committed", scope=__doc__))
