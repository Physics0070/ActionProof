export function Hairline({ strong = false }: { strong?: boolean }) {
  return <hr className={strong ? "hairline hairline-strong" : "hairline"} />;
}
