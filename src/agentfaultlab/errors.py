"""Attribution shared without importing the runner into provider adapters."""


class ProviderFailure(Exception):
    def __init__(self, message, code="provider_failure", input_tokens=None, output_tokens=None):
        super().__init__(message)
        self.code = code
        self.input_tokens, self.output_tokens = input_tokens, output_tokens
