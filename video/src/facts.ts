import D from "./data.generated.json";
// Every value shown in the video is read from here (generated from the real demo log, eval/results.json, audit run, console API).
const field = (card: string[], key: string) => (card.find((r) => r.startsWith(key + ":")) ?? "").slice(key.length + 1).trim();
const card1 = D.b1.card as string[];
export const amount = field(card1, "amount").replace(/\s*\[.*$/, "");        // 4800.00
export const variance = field(card1, "variance").replace(/\s*\[.*$/, "");    // 500.00
const req: any = (D as any).request;
// PO total: the console API's recorded value; fall back to the derivation (amount - variance) only if it was not recorded.
export const poTotal: string = req?.po_total ?? (Number(amount) - Number(variance)).toFixed(2);
export const invoiceId = "INV-2048";
export const money = (s: string) => "$" + Number(s).toLocaleString("en-US", { minimumFractionDigits: 2 });
export const moneyShort = (s: string) => "$" + Number(s).toLocaleString("en-US");
export const rule = field(card1, "rule");                                     // AP-INV-04 (> 100)
export const ruleId = rule.split(" ")[0];
export { D };

const b4c = (D.b4.lines as string[]).find((l) => l.startsWith("committed for")) ?? "";
export const capAmt = (b4c.match(/cap ([\d.]+)/) ?? [])[1] ?? "";
export const raceAmt = ((D.b4.lines as string[]).find((l) => l.startsWith("agent-7 spends")) ?? "").match(/spends ([\d.]+)/)?.[1] ?? "";
export const attacksN = D.eval.arms[0].n;
