/**
 * Zod mirrors of the API's Pydantic response schemas.
 *
 * WHY validate a response we already control:
 * CLAUDE.md's rule — "every agent output is validated against a schema before
 * being passed to the next node, no raw string handoffs" — doesn't stop at the
 * process boundary. The browser is just the last node in the graph. A
 * `fetch().json()` cast to a TypeScript interface is a *lie the compiler can't
 * catch*: TS types vanish at runtime, so a drifted API silently renders
 * `undefined` into the DOM. Parsing with Zod turns that into a loud, located
 * error at the boundary — the same guarantee the Python side already has.
 *
 * These mirror `apps/api/agents/synthesizer_agent.py` (ResearchNote, NoteClaim),
 * `apps/api/retrieval/types.py` (Citation), `apps/api/agents/quant_agent.py`
 * (QuantSignal), and `apps/api/retrieval/sources.py` (SourceDocument).
 *
 * Parity is currently maintained by hand, and drift is caught at runtime by the
 * `schema` branch of `ApiError` rather than at build time — an honest tradeoff,
 * not a solved problem. See `packages/shared-types/README.md` for why generating
 * these from the API's OpenAPI document is deferred rather than done now.
 */
import { z } from "zod";

/** retrieval/types.py :: Confidence */
export const confidenceSchema = z.enum(["high", "medium", "low", "none"]);
export type Confidence = z.infer<typeof confidenceSchema>;

/** agents/types.py :: ClaimStance */
export const claimStanceSchema = z.enum(["bull", "bear"]);
export type ClaimStance = z.infer<typeof claimStanceSchema>;

/** fact_checker_agent.py :: ClaimLabel — uppercase on the wire, deliberately. */
export const claimLabelSchema = z.enum([
  "SUPPORTED",
  "CONTRADICTED",
  "UNVERIFIABLE",
]);
export type ClaimLabel = z.infer<typeof claimLabelSchema>;

/** quant_agent.py :: QuantDirection */
export const quantDirectionSchema = z.enum(["bullish", "bearish", "neutral"]);
export type QuantDirection = z.infer<typeof quantDirectionSchema>;

/**
 * retrieval/types.py :: Citation
 *
 * `source_type` is a bare `str` on the Python side (documented as "'chunk' or
 * 'table'"). We narrow it to the enum the resolver actually accepts, so an
 * unrenderable citation fails here rather than as a 422 from /sources later.
 */
export const citationSchema = z.object({
  source_type: z.enum(["chunk", "table"]),
  source_id: z.number().int(),
  filing_id: z.number().int().nullable().default(null),
  page_number: z.number().int().nullable().default(null),
  similarity: z.number().nullable().default(null),
});
export type Citation = z.infer<typeof citationSchema>;

/** synthesizer_agent.py :: NoteClaim */
export const noteClaimSchema = z.object({
  text: z.string(),
  stance: claimStanceSchema,
  label: claimLabelSchema,
  citations: z.array(citationSchema),
});
export type NoteClaim = z.infer<typeof noteClaimSchema>;

/** quant_agent.py :: QuantSignal */
export const quantSignalSchema = z.object({
  ticker: z.string(),
  direction: quantDirectionSchema,
  confidence: z.number().min(0).max(1),
  horizon: z.string(),
  reasoning: z.string(),
  score: z.number().min(-1).max(1),
  series: z.array(z.number()),
  is_placeholder: z.boolean(),
  note: z.string(),
});
export type QuantSignal = z.infer<typeof quantSignalSchema>;

/** synthesizer_agent.py :: ResearchNote — the endpoint's top-level contract. */
export const researchNoteSchema = z.object({
  ticker: z.string(),
  thesis_summary: z.string(),
  key_supported_claims: z.array(noteClaimSchema),
  key_disputed_or_unverifiable_claims: z.array(noteClaimSchema),
  quant_signal: quantSignalSchema,
  citations: z.array(citationSchema),
});
export type ResearchNote = z.infer<typeof researchNoteSchema>;

/** retrieval/sources.py :: ChunkSource */
export const chunkSourceSchema = z.object({
  text: z.string(),
  chunk_index: z.number().int(),
});
export type ChunkSource = z.infer<typeof chunkSourceSchema>;

/**
 * retrieval/sources.py :: TableSource
 *
 * `columns`/`rows` are untyped JSONB on the Python side; we mirror that honestly
 * as unknown-cell arrays rather than pretending every cell is a string. The
 * renderer coerces for display — see `components/SourcePanel.tsx`.
 */
export const tableSourceSchema = z.object({
  columns: z.array(z.unknown()),
  rows: z.array(z.array(z.unknown())),
  table_index: z.number().int(),
});
export type TableSource = z.infer<typeof tableSourceSchema>;

/** retrieval/sources.py :: SourceDocument */
export const sourceDocumentSchema = z.object({
  source_type: z.enum(["chunk", "table"]),
  source_id: z.number().int(),
  filing_id: z.number().int(),
  company: z.string().nullable().default(null),
  ticker: z.string().nullable().default(null),
  file_name: z.string(),
  page_number: z.number().int().nullable().default(null),
  chunk: chunkSourceSchema.nullable().default(null),
  table: tableSourceSchema.nullable().default(null),
});
export type SourceDocument = z.infer<typeof sourceDocumentSchema>;
