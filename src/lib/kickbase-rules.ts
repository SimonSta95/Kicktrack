export const DEFAULT_SQUAD_LIMIT = 18;
export const KICKBASE_CREDIT_RATIO = 0.33;

export function formatCreditLimitLabel() {
  return `${Math.round(KICKBASE_CREDIT_RATIO * 100)}%-Grenze`;
}
