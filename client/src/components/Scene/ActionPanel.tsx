// The in-chat action panel — the primary text-adventure interaction. Numbered
// choice options (scripted on the opening beat, AI-generated after each
// narrator beat) plus the ↻ REROLL that regenerates them. The fixed actions
// live in the Composer, under the "OR DO SOMETHING ELSE:" header.

export function ActionPanel({
  options,
  optionRules,
  isOpening,
  suggestionsEnabled,
  loading,
  attempted,
  disabled,
  onPick,
  onReroll,
}: {
  options: string[]
  optionRules: string[]
  isOpening: boolean
  suggestionsEnabled: boolean
  loading: boolean
  attempted: boolean
  disabled: boolean
  onPick: (option: string) => void
  onReroll: () => void
}) {
  return (
    <div className="mr-auto w-full max-w-[85%] max-lg:max-w-full flex flex-col gap-1.5 pl-1 pt-1">
      {!isOpening && suggestionsEnabled && loading && (
        <span className="font-ui text-[10px] tracking-wider text-textdim animate-pulse px-1 py-1">
          WEIGHING YOUR OPTIONS ···
        </span>
      )}
      {!isOpening && suggestionsEnabled && !loading &&
        options.length === 0 && attempted && (
        <span className="font-ui text-[10px] tracking-wider text-textdim px-1 py-1">
          NO OPTIONS CAME THROUGH — ↻ REROLL TO TRY AGAIN
        </span>
      )}
      {!loading && options.map((s, i) => (
        <button
          key={`${i}-${s}`}
          type="button"
          disabled={disabled}
          onClick={() => onPick(s)}
          title={!isOpening ? optionRules[i] : undefined}
          className="group text-left font-body text-sm text-text2 border border-line rounded-md bg-bg2/40 px-3.5 py-2 hover:border-gold hover:text-text hover:bg-gold/5 transition-colors disabled:opacity-40"
        >
          <span className="text-golddeep group-hover:text-gold mr-2 font-ui text-[12px]">{i + 1}.</span>{s}
        </button>
      ))}

      {/* Reroll sits with the options it regenerates. */}
      {!isOpening && suggestionsEnabled && (
        <div className="pt-0.5">
          <button
            type="button"
            title="Reroll the generated options"
            disabled={disabled || loading}
            onClick={onReroll}
            className="font-ui text-[10px] tracking-wider text-textdim border border-line rounded-sm px-2 py-1 hover:text-gold hover:border-gold/50 transition-colors disabled:opacity-40"
          >
            ↻ REROLL
          </button>
        </div>
      )}
    </div>
  )
}
