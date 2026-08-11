"use client";

import { memo, useEffect, useState } from "react";
import type {
  AbilitySummary,
  DeathRecap,
  Encounter,
  EncounterAbility,
  FilteredContributor,
} from "@/lib/types";
import { trustAll, trustMember } from "@/lib/api";
import { usePanelPrefs } from "@/lib/panelPrefs";

const fmt = (n: number) => n.toLocaleString("en-US");

/** An EQL group holds four — not the six of the game it reimagines. */
const GROUP_CAP = 4;

function fightLabel(idx: number, enc: Encounter): string {
  if (idx === 0) return enc.active ? "Active" : "Last fight";
  return idx === 1 ? "1 fight ago" : `${idx} fights ago`;
}

function AbilityTable({ abilities, petSection }: { abilities: EncounterAbility[]; petSection?: boolean }) {
  return (
    <table className="enc-table">
      <thead>
        <tr>
          <th scope="col">Ability</th>
          <th scope="col" title="Successful hits · ✦ crits · ◇ staggers · initials = Slay Undead / Finishing Blow etc">×</th>
          <th scope="col">Avg</th>
          <th scope="col">Total</th>
          <th scope="col">DPS</th>
        </tr>
      </thead>
      <tbody>
        {abilities.map((a) => (
          <tr key={a.name} data-kind={a.kind}>
            <td className="enc-name" title={`${a.hits} hit${a.hits === 1 ? "" : "s"}`}>
              <span className="enc-rule" aria-hidden />
              {petSection ? a.name.replace(/^Pet: /, "") : a.name}
              {a.kind === "dot" && <span className="enc-tag">{a.kind}</span>}
              {a.kind === "ds" && <span className="enc-tag">ds</span>}
              {!petSection && a.kind === "pet" && (
                <span className="enc-tag">{a.kind}</span>
              )}
            </td>
            <td className="enc-count">
              {a.hits}
              {(a.crits ?? 0) > 0 && <span className="enc-crit"> ✦{a.crits}</span>}
              {(a.stuns ?? 0) > 0 && (
                <span className="enc-stun" title={`${a.stuns} staggered`}> ◇{a.stuns}</span>
              )}
              {a.mods &&
                Object.entries(a.mods).map(([m, n]) => (
                  <span key={m} className="enc-mod" title={`${m} ×${n}`}>
                    {" "}
                    {modInitials(m)}
                    {n}
                  </span>
                ))}
            </td>
            <td>{fmt(a.avg)}</td>
            <td>{fmt(a.total)}</td>
            <td>{a.dps}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Damage breakdown for the last 5 pulls. The arrows step back through
 *  recent encounters; the aggregate below sums abilities across all of them
 *  to surface which abilities actually hit hardest over time. */
/** "Slay Undead" -> "SU". A 300px-wide column cannot carry the full tag,
 *  and the count already sits beside it; the title attribute spells it out. */
function modInitials(mod: string) {
  return mod.split(/\s+/).map((w) => w[0]).join("");
}

export const EncounterPanel = memo(function EncounterPanel({
  encounters,
  summary,
  lastDeath,
  filtered,
}: {
  encounters: Encounter[];
  summary: AbilitySummary | null;
  lastDeath: DeathRecap | null;
  filtered?: FilteredContributor[];
}) {
  // Names the player has ruled on this render, so a row leaves immediately
  // instead of lingering until the next snapshot lands.
  const [ruled, setRuled] = useState<Record<string, boolean>>({});
  const { show } = usePanelPrefs();
  // Adding everyone can push the roster past what a group holds, and a
  // wrong name credits damage that is not yours -- so that one asks twice.
  // Ignoring everyone is reversible by any join, invite or group line, so
  // it does not.
  const [confirmAdd, setConfirmAdd] = useState(false);
  // Anchor the viewed pull by its start time so history shifting underneath
  // (a new fight starting) doesn't yank the panel to a different fight.
  const [viewStarted, setViewStarted] = useState<string | null>(null);

  let idx = viewStarted ? encounters.findIndex((e) => e.started === viewStarted) : 0;
  if (idx < 0) idx = 0;
  const enc = encounters[idx] ?? null;

  useEffect(() => {
    if (viewStarted && !encounters.some((e) => e.started === viewStarted)) {
      setViewStarted(null); // the viewed pull aged out of the 5-fight buffer
    }
  }, [encounters, viewStarted]);

  const step = (d: number) => {
    const next = Math.min(Math.max(idx + d, 0), encounters.length - 1);
    setViewStarted(next === 0 ? null : encounters[next].started);
  };

  const foes = enc?.foes ?? [];
  const slain = foes.filter((f) => f.slain).length;
  const [scale, setScale] = useState(1);
  // Collapsible for the same reason the ledger is: on a narrow screen this
  // panel is the widest thing competing with the Atlas, and someone reading
  // a map or a quest list does not need a per-ability breakdown beside it.
  const [open, setOpen] = useState(true);
  useEffect(() => {
    setOpen(localStorage.getItem("eql.encOpen") !== "0");
  }, []);
  const toggleOpen = () => {
    setOpen((v) => {
      localStorage.setItem("eql.encOpen", v ? "0" : "1");
      window.dispatchEvent(new Event("eql:collapse"));
      return !v;
    });
  };
  useEffect(() => {
    const s = parseFloat(localStorage.getItem("eql.encScale") ?? "1");
    if (s >= 0.8 && s <= 1.6) setScale(s);
  }, []);
  const bumpScale = (d: number) => {
    setScale((v) => {
      const n = Math.min(1.6, Math.max(0.8, Math.round((v + d) * 20) / 20));
      localStorage.setItem("eql.encScale", String(n));
      return n;
    });
  };

  return (
    <section className="panel enc-panel" data-collapsed={open ? undefined : "1"}>
      <div className="panel-title">
        Encounter
        <span className="font-scale" aria-label="Encounter text size">
          <button type="button" onClick={() => bumpScale(-0.1)} title="Smaller text">A−</button>
          <button type="button" onClick={() => bumpScale(0.1)} title="Larger text">A+</button>
        </span>
        <button
          type="button"
          className="ledger-collapse"
          onClick={toggleOpen}
          title={open ? "Collapse the encounter panel to just this bar" : "Expand it"}
        >
          {open ? "▾ hide" : "▸ show"}
        </button>
        {enc && (
          <span className="enc-nav">
            <button type="button" onClick={() => step(1)}
                    disabled={idx >= encounters.length - 1} aria-label="Older fight">
              ‹
            </button>
            <span className="enc-status" data-active={enc.active}>
              {fightLabel(idx, enc)}
              {encounters.length > 1 ? ` · ${idx + 1}/${encounters.length}` : ""}
            </span>
            <button type="button" onClick={() => step(-1)}
                    disabled={idx === 0} aria-label="Newer fight">
              ›
            </button>
          </span>
        )}
      </div>
      {open && (
      <div className="panel-body" style={{ zoom: scale }}>
        {!enc ? (
          <p className="chat-empty">
            No encounter yet. The breakdown appears when you enter combat, and
            the last five pulls stay browsable here.
          </p>
        ) : (
          <>
            <div className="enc-summary">
              <div className="enc-target">
                {foes.length > 1
                  ? `${foes.length} foes${slain > 0 ? ` - ${slain} slain` : ""}`
                  : enc.target ?? "Unknown foe"}
              </div>
              <div className="enc-meta">
                {enc.duration}s · {fmt(enc.total_damage)} dmg ·{" "}
                <span className="enc-dps">{enc.dps} DPS</span>
              </div>
              {enc.damage_taken > 0 && (
                <div className="enc-taken">{fmt(enc.damage_taken)} taken</div>
              )}
              {(() => {
                const d = enc.defense ?? {};
                const avoided = Object.values(d).reduce((a, b) => a + b, 0);
                const attacks = avoided + (enc.in_hits ?? 0);
                if (!attacks || !show("encounter", "defense")) return null;
                const parts = ["dodge", "parry", "block", "riposte", "miss"]
                  .filter((k) => d[k])
                  .map((k) => `${k} ${d[k]}`)
                  .join(" · ");
                return (
                  <div className="enc-defense">
                    defense {Math.round((100 * avoided) / attacks)}% —{" "}
                    {parts || "none"} <span className="adv-cls">of {attacks} attacks</span>
                  </div>
                );
              })()}
              {show("encounter", "defense") && enc.resists && Object.keys(enc.resists).length > 0 && (
                <div className="enc-defense">
                  resisted —{" "}
                  {Object.entries(enc.resists)
                    .map(([sp, n]) => (n > 1 ? `${sp} ×${n}` : sp))
                    .join(" · ")}
                </div>
              )}
              {show("encounter", "timeline") && (enc.timeline?.length ?? 0) > 2 && (
                <div className="enc-timeline" aria-label="Damage over the fight (2s buckets)">
                  {(() => {
                    const tl = enc.timeline ?? [];
                    const top = Math.max(...tl, 1);
                    return tl.map((v, i) => (
                      <span
                        key={i}
                        className="enc-tl-bar"
                        style={{ height: `${Math.max(2, Math.round((v / top) * 22))}px` }}
                      />
                    ));
                  })()}
                </div>
              )}
              {foes.length > 1 && (
                <ul className="enc-foes" aria-label="Foes in this encounter">
                  {foes.map((f) => (
                    <li key={f.name} data-slain={f.slain}>
                      <span className="enc-foe-name">{f.name}</span>
                      <span className="enc-foe-dmg">{fmt(f.damage)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {show("encounter", "abilities") && (
              <AbilityTable abilities={enc.abilities.filter((a) => a.kind !== "pet")} />
            )}
            {show("encounter", "pet") && enc.abilities.some((a) => a.kind === "pet") && (
              <div className="enc-agg">
                <h3>
                  Pet ·{" "}
                  {fmt(enc.abilities.filter((a) => a.kind === "pet")
                    .reduce((s, a) => s + a.total, 0))}
                </h3>
                <AbilityTable
                  abilities={enc.abilities.filter((a) => a.kind === "pet")}
                  petSection
                />
              </div>
            )}

            {show("encounter", "heals") && enc.heals.length > 0 && (
              <div className="enc-agg">
                <h3>Healing · {fmt(enc.total_healing)}</h3>
                <AbilityTable abilities={enc.heals} />
              </div>
            )}

            {summary && summary.encounters > 1 && (
              <div className="enc-agg">
                <h3>
                  Across last {summary.encounters} fights · {summary.duration}s in combat
                </h3>
                <AbilityTable abilities={summary.abilities.filter((a) => a.kind !== "pet")} />
                {summary.abilities.some((a) => a.kind === "pet") && (
                  <>
                    <div className="adv-sub" style={{ marginTop: 10 }}>Pet</div>
                    <AbilityTable
                      abilities={summary.abilities.filter((a) => a.kind === "pet")}
                      petSection
                    />
                  </>
                )}
                {summary.heals.length > 0 && (
                  <>
                    <div className="adv-sub" style={{ marginTop: 10 }}>Healing</div>
                    <AbilityTable abilities={summary.heals} />
                  </>
                )}
              </div>
            )}

            {show("encounter", "filtered") && (filtered ?? []).some((f) => !ruled[f.name]) && (
              <div className="enc-agg enc-filtered">
                <h3>Not counted</h3>
                <p className="enc-filtered-why">
                  Damage from people we can&apos;t confirm are in your group. EQL only lets
                  the tagger&apos;s group hurt a mob, so anyone in most of your fights is
                  grouped — a passer-by on a same-named mob shows up once or twice.
                  Names drop off on their own once they stop hitting your targets.
                  Rows marked <span className="enc-tag">pet?</span> have never shown up in a
                  /who and have never spoken, so they are most likely someone&apos;s pet —
                  they are listed last and are usually safe to ignore.
                </p>
                <table className="enc-table">
                  <thead>
                    <tr>
                      <th scope="col">Name</th>
                      <th scope="col">In your fights</th>
                      <th scope="col">Damage</th>
                      <th scope="col">
                        <span className="sr-only">Add to group or ignore</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {(filtered ?? [])
                      .filter((f) => !ruled[f.name])
                      .map((f) => (
                        <tr key={f.name} data-dim={f.pet ? "1" : undefined}>
                          <td className="enc-name">
                            <span className="enc-rule" aria-hidden />
                            {f.name}
                            {f.pet && (
                              <span
                                className="enc-tag"
                                title="Never appeared in a /who and has never spoken — most likely someone's pet. One word in chat clears this."
                              >
                                pet?
                              </span>
                            )}
                          </td>
                          <td>
                            {f.fights} <span className="enc-share">({f.share}%)</span>
                          </td>
                          <td>{fmt(f.damage)}</td>
                          <td className="enc-trust-cell">
                            {(["add", "ignore"] as const).map((act) => (
                              <button
                                key={act}
                                type="button"
                                className="enc-trust"
                                data-act={act}
                                title={
                                  act === "add"
                                    ? `Count ${f.name}'s damage — they are in your group`
                                    : `Hide ${f.name} until a join, invite or group chat proves otherwise`
                                }
                                onClick={() => {
                                  setRuled((r) => ({ ...r, [f.name]: true }));
                                  trustMember(f.name, act).catch(() =>
                                    setRuled((r) => {
                                      const n = { ...r };
                                      delete n[f.name];
                                      return n;
                                    }),
                                  );
                                }}
                              >
                                {act === "add" ? "Add" : "Ignore"}
                              </button>
                            ))}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
                <div className="enc-bulk">
                  <button
                    type="button"
                    className="enc-trust"
                    data-act={confirmAdd ? "warn" : "add"}
                    onClick={() => {
                      const names = (filtered ?? []).filter((f) => !ruled[f.name]);
                      if (!confirmAdd && names.length > GROUP_CAP) {
                        setConfirmAdd(true);
                        return;
                      }
                      setConfirmAdd(false);
                      setRuled((r) => {
                        const n = { ...r };
                        names.forEach((f) => (n[f.name] = true));
                        return n;
                      });
                      trustAll("add").catch(() => setRuled({}));
                    }}
                  >
                    {confirmAdd
                      ? `Add all anyway — that is more than a group of ${GROUP_CAP}`
                      : "Add all"}
                  </button>
                  <button
                    type="button"
                    className="enc-trust"
                    data-act="ignore"
                    onClick={() => {
                      setConfirmAdd(false);
                      setRuled((r) => {
                        const n = { ...r };
                        (filtered ?? []).forEach((f) => (n[f.name] = true));
                        return n;
                      });
                      trustAll("ignore").catch(() => setRuled({}));
                    }}
                  >
                    Ignore all
                  </button>
                </div>
              </div>
            )}

            {show("encounter", "group") && enc.allies.length > 1 && (
              <div className="enc-agg">
                <h3>Group — this fight</h3>
                <table className="enc-table">
                  <thead>
                    <tr>
                      <th scope="col">Member</th>
                      <th scope="col">Total</th>
                      <th scope="col">DPS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {enc.allies.map((a) => (
                      <tr key={a.name} data-you={a.name === "You"}>
                        <td className="enc-name">
                          <span className="enc-rule" aria-hidden />
                          {a.name}
                          {a.is_pet && <span className="enc-tag">pet</span>}
                          {!a.is_pet && (a.level != null || a.classes) && (
                            <span className="enc-member-meta">
                              {a.level ?? "?"} {a.classes ?? ""}
                            </span>
                          )}
                        </td>
                        <td>{fmt(a.damage)}</td>
                        <td>{a.dps}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
        {lastDeath && (
          <div className="enc-agg enc-death">
            <h3>
              Last death · {new Date(lastDeath.ts).toLocaleTimeString("en-GB", { hour12: false })} · slain by {lastDeath.killer}
            </h3>
            <ul className="death-recap">
              {lastDeath.hits.map((hit, i) => (
                <li key={i}>
                  <span>{hit.attacker} · {hit.source}</span>
                  <span className="death-dmg">−{fmt(hit.damage)}</span>
                </li>
              ))}
            </ul>
            <div className="death-total">
              {fmt(lastDeath.total)} damage in the final 15s
            </div>
          </div>
        )}
      </div>
      )}
    </section>
  );
});