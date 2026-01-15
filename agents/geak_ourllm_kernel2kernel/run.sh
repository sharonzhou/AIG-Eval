export OPENAI_API_KEY="${AMD_GATEWAY_API_KEY}"
export MODEL_API_URL='https://llm-api.amd.com'
clear
python3 main.py
unset OPENAI_API_KEY
unset MODEL_API_URL
