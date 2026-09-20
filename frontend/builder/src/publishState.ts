/**
 * What the toolbar says about this flow, and whether Publish is worth offering.
 *
 * Pulled out of the component so the cases that are awkward to reach by
 * clicking -- a reload onto an already-published version, an archived flow, an
 * edit in flight over a live one -- are assertable as a table.
 *
 * The rule this file exists to keep: the label describes what the *server* last
 * told us, never what we hope happened. `save.version.published` is the flag
 * the publish response and the detail response both carry, so a reload and a
 * fresh publish arrive at the same label by the same route.
 */
import i18n from "./i18n";
import { UNSAVED } from "./persistence/autosave";
import type { SaveSlice } from "./store/store";

export type PublishTone = "success" | "warning" | "plain";

export interface PublishView {
  /** The status text beside the Publish button. */
  label: string;
  tone: PublishTone;
  /** The live version, when it is not the one the label already names. */
  liveChip: string | null;
  publishDisabled: boolean;
  publishLabel: string;
  /** Why the button is off, for its `title`. Null when it is on. */
  publishHint: string | null;
}

// A function, not a table built once at module load: the labels have to read
// in whatever language is active *now*, the same reason Django's own
// module-level copy in this rollout uses gettext_lazy rather than gettext.
// i18n.t() called at import time would freeze every label in whatever
// language was active before main.tsx's setBuilderLocale() ever runs.
function saveCopy(state: string): string {
  const known: Record<string, string> = {
    clean: i18n.t("publishState.save.clean"),
    dirty: i18n.t("publishState.save.dirty"),
    saving: i18n.t("publishState.save.saving"),
    saved: i18n.t("publishState.save.saved"),
    rejected: i18n.t("publishState.save.rejected"),
    error: i18n.t("publishState.save.error"),
  };
  return known[state] ?? state;
}

// Borrowed from the autosave rather than restated: "the server does not have
// what you are looking at" is one fact, and two copies of it would disagree the
// first time a save state is added.
const PENDING: ReadonlySet<string> = new Set(UNSAVED);

export function publishView(save: SaveSlice, flowStatus: string | undefined): PublishView {
  const copy = saveCopy(save.state);
  const pending = PENDING.has(save.state);
  const live = save.publishedVersion;
  const liveNow = !pending && save.version?.published === true;

  if (flowStatus === "archived") {
    // Archiving does not unpublish, and publishing un-archives (services.publish
    // sets status back to ACTIVE), so the button stays live and says so.
    return {
      label: i18n.t("publishState.archived"),
      tone: "warning",
      liveChip: live ? i18n.t("publishState.liveChip", { version: live.version }) : null,
      publishDisabled: false,
      publishLabel: i18n.t("publishState.setLive"),
      publishHint: null,
    };
  }

  if (liveNow) {
    return {
      label: i18n.t("publishState.liveLabel", { version: save.version?.version }),
      tone: "success",
      liveChip: null,
      publishDisabled: true,
      // Still "Set live", not "Live": the status beside it already says
      // `Live · v2`, and a button repeating the word says nothing about what
      // pressing it would do. Disabled plus the hint carries that.
      publishLabel: i18n.t("publishState.setLive"),
      publishHint: i18n.t("publishState.alreadyLiveHint"),
    };
  }

  return {
    // No version number while an edit is pending over a published one: the next
    // save opens version n+1, so printing n here would name the *live* version
    // as though it were the draft in front of you.
    label:
      pending && live
        ? copy
        : save.version
          ? i18n.t("publishState.draftLabel", { save: copy, version: save.version.version })
          : copy,
    tone: "plain",
    liveChip: live ? i18n.t("publishState.liveChip", { version: live.version }) : null,
    publishDisabled: false,
    publishLabel: i18n.t("publishState.setLive"),
    publishHint: null,
  };
}
