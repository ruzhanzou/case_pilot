from collections.abc import Callable

from casepilot_agent.contracts import AgentProvider, GenerationRequest, GenerationResult

ProgressCallback = Callable[[str, int, int], None]


class GenerationPipeline:
    def __init__(self, provider: AgentProvider) -> None:
        self.provider = provider

    def run(
        self,
        request: GenerationRequest,
        on_progress: ProgressCallback | None = None,
    ) -> GenerationResult:
        result = self.provider.generate(request)
        if on_progress:
            for index, stage in enumerate(result.stages, start=1):
                on_progress(stage, index, len(result.stages))
        return result
