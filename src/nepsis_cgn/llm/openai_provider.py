import openai

from .base import BaseLLMProvider


class OpenAIProvider(BaseLLMProvider):
    """
    A simple OpenAI Chat Completions provider for NepsisCGN.
    """

    def __init__(self, model: str = "gpt-4.1", temperature: float = 0.2):
        super().__init__()
        self.model = model
        self.temperature = temperature

    def generate(self, system_prompt: str, user_prompt: str):
        """
        Nepsis Supervisor calls this with (system_instruction, projection_context_prompt).
        """
        client = openai.OpenAI()

        response = client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        # Extract text result
        return response.choices[0].message["content"].strip()
