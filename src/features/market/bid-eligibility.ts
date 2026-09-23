import { DEFAULT_SQUAD_LIMIT, KICKBASE_CREDIT_RATIO, formatCreditLimitLabel } from "../../lib/kickbase-rules.ts";

export type BidEligibilityReason =
  | "INVALID_AMOUNT"
  | "BELOW_MARKET_VALUE"
  | "SQUAD_FULL"
  | "BUDGET_LIMIT"
  | "BUDGET_UNAVAILABLE";

export type BidEligibility = {
  allowed: boolean;
  reasons: BidEligibilityReason[];
  maximumBid: number | null;
  minimumBid: number | null;
  squadSlotsFree: number | null;
  minimumBalance: number | null;
  effectiveBalance: number | null;
  adjustedSquadValue: number | null;
};

export type BidEligibilityInput = {
  bid: number | null;
  marketValue: number | null;
  squadValue: number;
  balanceAfterActiveBids: number | null;
  existingBid?: number | null;
  squadSize: number | null;
  squadLimit: number | null;
};

export function resolveBalanceAfterActiveBids(
  budget: number | null,
  budgetAfterActiveBids: number | null,
  visibleActiveBidTotal: number,
) {
  if (budgetAfterActiveBids != null) return budgetAfterActiveBids;
  if (budget == null) return null;
  return Math.trunc(budget) - Math.max(0, Math.trunc(visibleActiveBidTotal || 0));
}

export function calculateBidCapacity(
  squadValue: number,
  balanceAfterActiveBids: number | null,
  existingBid = 0,
) {
  if (balanceAfterActiveBids == null) {
    return {
      effectiveBalance: null,
      adjustedSquadValue: null,
      minimumBalance: null,
      maximumBid: null,
    };
  }

  const squad = Math.max(0, Math.trunc(squadValue || 0));
  const effectiveBalance = Math.trunc(balanceAfterActiveBids) + Math.max(0, Math.trunc(existingBid || 0));
  const adjustedSquadValue = Math.max(0, squad + Math.min(effectiveBalance, 0));
  const minimumBalance = -Math.floor(adjustedSquadValue * KICKBASE_CREDIT_RATIO);
  const maximumBid = Math.max(0, effectiveBalance - minimumBalance);

  return { effectiveBalance, adjustedSquadValue, minimumBalance, maximumBid };
}

export function evaluateBidEligibility(input: BidEligibilityInput): BidEligibility {
  const reasons: BidEligibilityReason[] = [];
  const bid = input.bid;
  const minimumBid = input.marketValue == null ? null : Math.max(0, Math.trunc(input.marketValue));
  const slotsFree = input.squadSize == null || input.squadLimit == null
    ? null
    : Math.max(0, input.squadLimit - input.squadSize);

  const capacity = calculateBidCapacity(
    input.squadValue,
    input.balanceAfterActiveBids,
    input.existingBid ?? 0,
  );

  if (bid == null || !Number.isFinite(bid) || bid <= 0) reasons.push("INVALID_AMOUNT");
  if (bid != null && minimumBid != null && bid < minimumBid) reasons.push("BELOW_MARKET_VALUE");
  if (slotsFree != null && slotsFree <= 0) reasons.push("SQUAD_FULL");
  if (capacity.maximumBid == null) reasons.push("BUDGET_UNAVAILABLE");
  else if (bid != null && bid > capacity.maximumBid) reasons.push("BUDGET_LIMIT");

  return {
    allowed: reasons.length === 0,
    reasons,
    maximumBid: capacity.maximumBid,
    minimumBid,
    squadSlotsFree: slotsFree,
    minimumBalance: capacity.minimumBalance,
    effectiveBalance: capacity.effectiveBalance,
    adjustedSquadValue: capacity.adjustedSquadValue,
  };
}

export function bidReasonLabel(reason: BidEligibilityReason) {
  switch (reason) {
    case "INVALID_AMOUNT": return "Bitte ein gültiges Gebot eingeben.";
    case "BELOW_MARKET_VALUE": return "Das Gebot muss mindestens dem aktuellen Marktwert entsprechen.";
    case "SQUAD_FULL": return `Dein Kader ist voll. Maximal ${DEFAULT_SQUAD_LIMIT} Spieler sind erlaubt.`;
    case "BUDGET_LIMIT": return `Das Gebot überschreitet deine lokale ${formatCreditLimitLabel()}.`;
    case "BUDGET_UNAVAILABLE": return "Die Budgetgrenze konnte gerade nicht verlässlich berechnet werden.";
  }
}
