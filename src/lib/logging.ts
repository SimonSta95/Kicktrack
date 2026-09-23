export const debugLog = (...args: unknown[]) => {
  if (import.meta.env.DEV) console.debug(...args);
};

export const warnLog = (...args: unknown[]) => {
  if (import.meta.env.DEV) console.warn(...args);
};
