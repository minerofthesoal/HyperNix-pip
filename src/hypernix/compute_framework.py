"""compute_framework.py — Hardware-agnostic multi-device training framework.

v0.70.0: Abstracts away CUDA, MPS, CPU, and handles DDP / ZeRO wrapping automatically.
"""
from __future__ import annotations

import os
from typing import Any

import torch
import torch.nn as nn


class ComputeArch:
    """Hardware architecture type."""
    CUDA = "cuda"
    MPS = "mps"
    CPU = "cpu"
    TPU = "tpu"
    SINGLE_GPU = "cuda"


class ComputeFramework:
    """A high-level framework for training models on different GPUs/CPUs/architectures.
    
    Automatically handles PyTorch DDP initialization, device placement,
    and fallback logic.
    """

    def __init__(
        self,
        local_rank: int | str = -1,
        world_size: int = 1,
        use_ddp: bool = False,
        use_fsdp: bool = False,
        zero_stage: int = 0,
        use_lazy_suzan: bool = False,
        lazy_suzan_config: Any | None = None,
    ) -> None:
        if isinstance(local_rank, str):
            self.arch = local_rank
            self.local_rank = -1
        else:
            self.local_rank = local_rank
            self.arch = self._detect_arch()
            
        self.world_size = world_size
        self.use_ddp = use_ddp
        self.use_fsdp = use_fsdp
        self.zero_stage = zero_stage
        self.use_lazy_suzan = use_lazy_suzan
        self.lazy_suzan_config = lazy_suzan_config
        
        self.device = self._setup_device()
        self.is_main_process = self.local_rank in [-1, 0]

    def _detect_arch(self) -> str:
        if torch.cuda.is_available():
            return ComputeArch.CUDA
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return ComputeArch.MPS
        return ComputeArch.CPU

    def _setup_device(self) -> torch.device:
        if self.use_ddp or self.use_fsdp:
            if "LOCAL_RANK" in os.environ:
                self.local_rank = int(os.environ["LOCAL_RANK"])
            if "WORLD_SIZE" in os.environ:
                self.world_size = int(os.environ["WORLD_SIZE"])
            
            if self.arch == ComputeArch.CUDA and self.local_rank != -1:
                torch.cuda.set_device(self.local_rank)
                torch.distributed.init_process_group(backend="nccl")
                return torch.device(f"cuda:{self.local_rank}")
                
        if self.arch == ComputeArch.CUDA:
            return torch.device("cuda")
        elif self.arch == ComputeArch.MPS:
            return torch.device("mps")
        return torch.device("cpu")

    def prepare_model(self, model: nn.Module) -> nn.Module:
        """Move model to the correct device and wrap it in DDP/FSDP if requested."""
        model = model.to(self.device)
        
        if getattr(self, "use_lazy_suzan", False):
            from .lazy_suzan import LazySusan
            self.lazy_suzan = LazySusan(model, getattr(self, "lazy_suzan_config", None))
        
        if self.use_fsdp and self.arch == ComputeArch.CUDA:
            import functools

            from torch.distributed.fsdp import FullyShardedDataParallel as FSDP
            from torch.distributed.fsdp.wrap import transformer_auto_wrap_policy

            # Try to detect MPT blocks for correct auto-wrapping
            mpt_block_class = self._detect_mpt_block(model)
            if mpt_block_class:
                auto_wrap_policy = functools.partial(
                    transformer_auto_wrap_policy,
                    transformer_layer_cls={mpt_block_class},
                )
            else:
                auto_wrap_policy = None

            # Map zero_stage to FSDP ShardingStrategy
            from torch.distributed.fsdp import ShardingStrategy
            if self.zero_stage == 1:
                strategy = ShardingStrategy.SHARD_GRAD_OP
            elif self.zero_stage == 2:
                strategy = ShardingStrategy.SHARD_GRAD_OP  # ZeRO-2 equivalent
            elif self.zero_stage == 3:
                strategy = ShardingStrategy.FULL_SHARD
            else:
                strategy = ShardingStrategy.NO_SHARD

            model = FSDP(
                model, 
                device_id=self.local_rank, 
                auto_wrap_policy=auto_wrap_policy,
                sharding_strategy=strategy
            )
            
        elif self.use_ddp and self.arch == ComputeArch.CUDA and self.local_rank != -1:
            from torch.nn.parallel import DistributedDataParallel as DDP
            model = DDP(model, device_ids=[self.local_rank], output_device=self.local_rank)
            
        return model

    def _detect_mpt_block(self, model: nn.Module) -> type | None:
        """Detect MPT transformer block class to ensure Wqkv isn't incorrectly sharded."""
        for module in model.modules():
            cls_name = module.__class__.__name__
            if "MPTBlock" in cls_name or "MPTForCausalLM" in cls_name:
                # Try to import MPTBlock if available in environment
                try:
                    from transformers.models.mpt.modeling_mpt import MPTBlock
                    return MPTBlock
                except ImportError:
                    pass
                return type(module)
        return None

    def prepare_optimizer(self, optimizer: torch.optim.Optimizer) -> torch.optim.Optimizer:
        """Hook to wrap optimizer for ZeRO stages if implemented manually."""
        return optimizer

    def initialize(self) -> None:
        """Initialize the compute framework. (No-op for backwards compatibility)"""
        pass

    def backward(self, loss: torch.Tensor) -> None:
        """Perform backward pass."""
        loss.backward()

    def step(self, optimizer: torch.optim.Optimizer) -> None:
        """Step optimizer and invoke LazySusan synchronization if active."""
        optimizer.step()
        if hasattr(self, "lazy_suzan"):
            self.lazy_suzan.step()

    def cleanup(self) -> None:
        """Destroy distributed process groups if any."""
        if (self.use_ddp or self.use_fsdp) and torch.distributed.is_initialized():
            torch.distributed.destroy_process_group()
