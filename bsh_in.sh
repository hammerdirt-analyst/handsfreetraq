python - << 'EOF'
from outlines.models.openai import OpenAIConfig, OpenAI
import inspect

print("OpenAIConfig signature:", inspect.signature(OpenAIConfig.__init__))
print("OpenAI signature:", inspect.signature(OpenAI.__init__))
EOF
