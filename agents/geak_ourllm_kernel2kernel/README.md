## Overview
This agent enables you to evaluation self-trained LLMs via vllm.

## Docker
You need to enter a docker that support VLLM. e.g. rlsys/rocm-6.3.4-patch:rocm6.3.4-numa-patch_ubuntu-22.04

## Downloads & install
- Clone this specific [GEAK_HIP](https://github.com/AMD-AGI/GEAK_HIP.git) repo into this folder and rename it to GEAK-agent. Other version of GEAK-HIP is currently not supported. git clone https://github.com/AMD-AGI/GEAK_HIP.git
- run install.sh in the root folder. It is ok if apt-get install gawk got error.

## Set API
Notice that you should set up a VLLM api first, like this
export VLLM_DISABLE_QUANTIZATION=1
model_path=YOUR MODEL PATH
"HIP_VISIBLE_DEVICES=0 vllm serve ${model_path} --host 0.0.0.0 --port 8001 --trust-remote-code --tensor-parallel-size 1 --quantization None --max-num-batched-tokens 65536  --gpu-memory-utilization 0.9 --max-model-len 32768"