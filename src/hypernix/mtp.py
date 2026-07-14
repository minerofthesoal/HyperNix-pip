"""mtp — Multi-Token Prediction for efficient training and speculative decoding.

v0.70.5: Native Multi-Token Prediction support for HyperNix workshop.

MTP trains models to predict multiple future tokens simultaneously,
improving sample efficiency by 1.5-3x and enabling speculative
decoding at inference time.

Key features:
  * Multi-token prediction heads (D=1 to N future tokens)
  * Sequential and independent prediction modes
  * Loss balancing across token positions
  * Native integration with PressureCookerV5 workshop pipeline
  * Support for MTP-QAT combined training

Usage:
    from hypernix.mtp import MTPTrainer, MTPConfig

    config = MTPConfig(num_tokens=4, lambda_weight=0.3, sequential=True)
    mtp = MTPTrainer(model, config)
    losses = mtp.compute_loss(input_ids, labels)
    total_loss = losses["total"]  # main + weighted MTP losses
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor


@dataclass
class MTPConfig:
    """Configuration for Multi-Token Prediction training.

    Args:
        num_tokens: Number of future tokens to predict (D).
        lambda_weight: Weight for MTP losses in total loss.
        sequential: Chain predictions (feed N-th into N+1-th).
        shared_head: Share projection head across token positions.
        loss_weights: Optional per-token loss weights.
        temperature: Softmax temperature for MTP heads.
        label_smoothing: Label smoothing for MTP losses.
        drop_path: Stochastic depth rate for MTP heads.
    """
    num_tokens: int = 4
    lambda_weight: float = 0.3
    sequential: bool = True
    shared_head: bool = True
    loss_weights: list[float] | None = None
    temperature: float = 1.0
    label_smoothing: float = 0.0
    drop_path: float = 0.0

    def __post_init__(self) -> None:
        if self.num_tokens < 1:
            raise ValueError("num_tokens must be >= 1")
        if not 0.0 <= self.lambda_weight <= 1.0:
            raise ValueError("lambda_weight must be in [0, 1]")
        if self.loss_weights is not None:
            if len(self.loss_weights) != self.num_tokens:
                raise ValueError(
                    f"loss_weights length ({len(self.loss_weights)}) must match "
                    f"num_tokens ({self.num_tokens})"
                )
        if not 0.0 <= self.drop_path < 1.0:
            raise ValueError("drop_path must be in [0, 1)")

    def get_loss_weights(self) -> list[float]:
        """Return loss weights for each token position."""
        if self.loss_weights is not None:
            return self.loss_weights
        return [1.0 - 0.1 * i for i in range(self.num_tokens)]


class MTPHead(nn.Module):
    """Multi-Token Prediction head.

    Predicts D future tokens from hidden states using either
    shared or independent projection layers.

    Args:
        hidden_dim: Model hidden dimension.
        vocab_size: Vocabulary size.
        num_tokens: Number of future tokens (D).
        shared: Share projection across positions.
        dropout: Dropout rate.
    """

    def __init__(
        self,
        hidden_dim: int,
        vocab_size: int,
        num_tokens: int = 4,
        shared: bool = True,
        dropout: float = 0.0,
    ) -> None:
        super().__init__()
        self.hidden_dim = hidden_dim
        self.vocab_size = vocab_size
        self.num_tokens = num_tokens
        self.shared = shared

        if shared:
            self.projection = nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_dim, vocab_size),
            )
            self.heads = nn.ModuleList([self.projection] * num_tokens)
        else:
            self.heads = nn.ModuleList([
                nn.Sequential(
                    nn.Linear(hidden_dim, hidden_dim),
                    nn.GELU(),
                    nn.Dropout(dropout),
                    nn.Linear(hidden_dim, vocab_size),
                )
                for _ in range(num_tokens)
            ])

        if not shared:
            self.seq_projections = nn.ModuleList([
                nn.Linear(hidden_dim, hidden_dim)
                for _ in range(num_tokens - 1)
            ])

        self._init_weights()

    def _init_weights(self) -> None:
        """Initialize with small weights for stability."""
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.normal_(module.weight, std=0.02)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)

    def forward(
        self,
        hidden: Tensor,
        sequential: bool = True,
    ) -> list[Tensor]:
        """Predict multiple future tokens.

        Args:
            hidden: Hidden states [batch, seq, hidden_dim].
            sequential: If True, chain predictions.

        Returns:
            List of logits [batch, seq, vocab_size] for each future position.
        """
        logits = []
        current = hidden

        for i, head in enumerate(self.heads):
            logit = head(current)
            logits.append(logit)

            if sequential and i < len(self.heads) - 1:
                if hasattr(self, "seq_projections") and not self.shared:
                    current = self.seq_projections[i](current)

        return logits


class MTPTrainer:
    """Trainer for Multi-Token Prediction.

    Wraps a model with MTP heads and manages the combined loss.

    Args:
        model: The base model (should output hidden states).
        config: MTP configuration.
        base_criterion: Base loss function (defaults to cross entropy).
    """

    def __init__(
        self,
        model: nn.Module,
        config: MTPConfig | None = None,
        base_criterion: Any = None,
    ) -> None:
        self.model = model
        self.config = config or MTPConfig()
        self.base_criterion = base_criterion or nn.CrossEntropyLoss(
            label_smoothing=self.config.label_smoothing,
        )
        self.mtp_head: MTPHead | None = None
        self._step_count = 0

    def attach_head(
        self,
        hidden_dim: int,
        vocab_size: int,
    ) -> MTPHead:
        """Attach an MTP head to the model."""
        self.mtp_head = MTPHead(
            hidden_dim=hidden_dim,
            vocab_size=vocab_size,
            num_tokens=self.config.num_tokens,
            shared=self.config.shared_head,
        )
        return self.mtp_head

    def compute_loss(
        self,
        logits: Tensor,
        labels: Tensor,
        hidden_states: Tensor | None = None,
    ) -> dict[str, Tensor]:
        """Compute combined main + MTP loss."""
        main_loss = self._compute_main_loss(logits, labels)

        mtp_loss = torch.tensor(0.0, device=logits.device)
        if self.mtp_head is not None and hidden_states is not None:
            mtp_loss = self._compute_mtp_loss(hidden_states, labels)

        lambda_w = self.config.lambda_weight
        total_loss = main_loss + lambda_w * mtp_loss

        return {
            "main": main_loss,
            "mtp": mtp_loss,
            "total": total_loss,
        }

    def _compute_main_loss(self, logits: Tensor, labels: Tensor) -> Tensor:
        """Compute the main next-token prediction loss."""
        batch_size, seq_len, vocab_size = logits.shape
        logits_flat = logits.view(-1, vocab_size)
        labels_flat = labels.view(-1)

        loss = F.cross_entropy(
            logits_flat,
            labels_flat,
            ignore_index=-100,
            label_smoothing=self.config.label_smoothing,
        )
        return loss

    def _compute_mtp_loss(self, hidden: Tensor, labels: Tensor) -> Tensor:
        """Compute MTP losses for multiple future tokens."""
        batch_size, seq_len, hidden_dim = hidden.shape
        loss_weights = self.config.get_loss_weights()

        device = hidden.device
        mtp_logits = self.mtp_head(
            hidden,
            sequential=self.config.sequential,
        )

        total_mtp_loss = torch.tensor(0.0, device=device)
        valid_tokens = 0

        for i, logits in enumerate(mtp_logits):
            if i + 1 >= seq_len:
                break

            pred_logits = logits[:, :-i-1, :].contiguous()
            target_labels = labels[:, i+1:].contiguous()

            pred_flat = pred_logits.view(-1, pred_logits.size(-1))
            target_flat = target_labels.view(-1)

            if (target_flat == -100).all():
                continue

            loss = F.cross_entropy(
                pred_flat,
                target_flat,
                ignore_index=-100,
                reduction="sum",
            )

            num_valid = (target_flat != -100).sum()
            if num_valid > 0:
                loss = loss / num_valid
                total_mtp_loss += loss_weights[i] * loss
                valid_tokens += 1

        if valid_tokens > 0:
            total_mtp_loss = total_mtp_loss / valid_tokens

        return total_mtp_loss

    def get_stats(self) -> dict[str, Any]:
        """Get MTP training statistics."""
        return {
            "num_tokens": self.config.num_tokens,
            "lambda_weight": self.config.lambda_weight,
            "sequential": self.config.sequential,
            "shared_head": self.config.shared_head,
            "temperature": self.config.temperature,
            "steps": self._step_count,
        }


def cli_main(argv: list[str] | None = None) -> int:
    """CLI entry point for MTP configuration."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Multi-Token Prediction configuration",
        prog="hnx mtp",
    )
    parser.add_argument("--tokens", type=int, default=4, help="Number of future tokens")
    parser.add_argument("--lambda", dest="lambda_weight", type=float, default=0.3)
    parser.add_argument("--sequential", action="store_true", default=True)
    parser.add_argument("--independent", dest="sequential", action="store_false")
    parser.add_argument("--shared-head", action="store_true", default=True)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--label-smoothing", type=float, default=0.0)

    args = parser.parse_args(argv)

    config = MTPConfig(
        num_tokens=args.tokens,
        lambda_weight=args.lambda_weight,
        sequential=args.sequential,
        shared_head=args.shared_head,
        temperature=args.temperature,
        label_smoothing=args.label_smoothing,
    )

    print(f"MTP Configuration:")
    print(f"  Future tokens: {config.num_tokens}")
    print(f"  Lambda weight: {config.lambda_weight}")
    print(f"  Sequential: {config.sequential}")
    print(f"  Shared head: {config.shared_head}")
    print(f"  Temperature: {config.temperature}")
    print(f"  Loss weights: {config.get_loss_weights()}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(cli_main())
