"""Allowlisted provider usage capture via LangChain's public callback interface."""

from langchain_core.callbacks import BaseCallbackHandler


class UsageCollector(BaseCallbackHandler):
    def __init__(self):
        self.started = 0
        self.failed = 0
        self.records = []
        self._ended = set()

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.started += 1

    def on_llm_error(self, error, **kwargs):
        self.failed += 1

    def on_llm_end(self, response, *, run_id, **kwargs):
        if str(run_id) in self._ended:
            return
        self._ended.add(str(run_id))
        usage = None
        for group in response.generations:
            for generation in group:
                message = getattr(generation, "message", None)
                candidate = getattr(message, "usage_metadata", None)
                if candidate:
                    usage = candidate
                    break
            if usage:
                break
        if not usage:
            raw = (response.llm_output or {}).get("token_usage", {})
            if "prompt_tokens" in raw and "completion_tokens" in raw:
                usage = {"input_tokens": raw["prompt_tokens"], "output_tokens": raw["completion_tokens"]}
        self.records.append({
            "input_tokens": usage.get("input_tokens") if usage else None,
            "output_tokens": usage.get("output_tokens") if usage else None,
        })

    def summary(self):
        complete = bool(self.records) and all(
            r["input_tokens"] is not None and r["output_tokens"] is not None for r in self.records)
        totals = ({k: sum(r[k] for r in self.records) for k in ("input_tokens", "output_tokens")}
                  if complete else None)
        return {"llm_calls_started": self.started, "llm_calls_failed": self.failed,
                "llm_calls_completed": len(self.records), "llm_tokens": totals,
                "usage_records": self.records,
                "usage_note": "Provider-reported completed calls only; missing/error billing is not inferred."}


def attach_usage(researcher, collector):
    """Attach to the model constructor through GPTR's existing config seam."""
    researcher.cfg.llm_kwargs = {**researcher.cfg.llm_kwargs,
                                "callbacks": [collector], "max_retries": 0, "timeout": 60}
