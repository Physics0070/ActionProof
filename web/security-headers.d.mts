export function buildCsp(opts?: { nonce?: string }): string;
export function cspWithNonce(nonce: string): string;
export const securityHeaders: { key: string; value: string }[];
export function headers(): Promise<{ source: string; headers: { key: string; value: string }[] }[]>;
