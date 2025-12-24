Note: Clone this specific [GEAK_HIP](https://github.com/AMD-AGI/GEAK_HIP.git) repo into this folder.
git clone https://github.com/AMD-AGI/GEAK_HIP.git
Other version of GEAK-HIP is currently not supported.

Also notice that you should set up a VLLM api first, like this 
"HIP_VISIBLE_DEVICES=0 vllm serve ${model_path} --host 0.0.0.0 --port 8001 --trust-remote-code --tensor-parallel-size 1 --quantization None --max-num-batched-tokens 65536  --gpu-memory-utilization 0.9 --max-model-len 32768"