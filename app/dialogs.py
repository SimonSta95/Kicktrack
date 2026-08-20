"""Dialog facade for the KickTrack desktop UI.

Concrete dialog implementations live in focused modules to keep dependencies and
review scope manageable while preserving the public import surface.
"""

from .action_dialogs import (
    FinancingScenarioDialog, LineupOptimizerDialog, ListingManagementDialog, LoginDialog,
    MarketBidDialog, MarketScannerDialog, MarketScoringInfoDialog, PortraitReviewDialog,
    PreseasonOptimizerDialog, SellPlayerDialog, SquadScoringInfoDialog,
)
from .manager_dialogs import ManagerComparisonDialog, ManagerDetailDialog, ManagerTransferDialog
from .player_dialogs import (
    MatchEventBreakdownDialog, PlayerComparisonDialog, PlayerDetailDialog,
    PlayerDetailTabsWindow, open_player_detail_window,
)

__all__ = [
    "FinancingScenarioDialog", "LineupOptimizerDialog", "ListingManagementDialog", "LoginDialog",
    "ManagerComparisonDialog", "ManagerDetailDialog", "ManagerTransferDialog", "MarketBidDialog",
    "MarketScannerDialog", "MarketScoringInfoDialog", "MatchEventBreakdownDialog",
    "PlayerComparisonDialog", "PlayerDetailDialog", "PlayerDetailTabsWindow", "PortraitReviewDialog",
    "PreseasonOptimizerDialog", "SellPlayerDialog", "SquadScoringInfoDialog", "open_player_detail_window",
]
