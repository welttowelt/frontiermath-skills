#!/usr/bin/env python3
"""Exact gate for the published Katz--Tao advanced-iteration recurrence."""

from __future__ import annotations

import json
from decimal import Decimal, getcontext
from fractions import Fraction


TARGET = Fraction(67, 40)
START = Fraction(7, 4)


def polynomial(value: Fraction) -> Fraction:
    return value**3 - 4 * value + 2


def recurrence(value: Fraction) -> Fraction:
    return (
        3 * value**2 + 2 * value - 2
    ) / (
        value**2 + 3 * value - 2
    )


def largest_root_decimal() -> Decimal:
    getcontext().prec = 40
    left = Decimal(3) / Decimal(2)
    right = Decimal(2)
    for _ in range(180):
        midpoint = (left + right) / 2
        value = midpoint**3 - 4 * midpoint + 2
        if value < 0:
            left = midpoint
        else:
            right = midpoint
    return (left + right) / 2


def main() -> int:
    target_polynomial = polynomial(TARGET)
    target_denominator = TARGET**2 + 3 * TARGET - 2
    target_step = recurrence(TARGET)
    iterates: list[dict[str, object]] = []
    value = START
    for iteration in range(8):
        iterates.append(
            {
                "iteration": iteration,
                "score": f"{value.numerator}/{value.denominator}",
                "decimal": float(value),
                "above_target": value > TARGET,
            }
        )
        value = recurrence(value)

    checks = {
        "target-polynomial-is-negative": target_polynomial < 0,
        "polynomial-is-increasing-from-target-to-two": (
            3 * TARGET**2 - 4 > 0
        ),
        "start-polynomial-is-positive": polynomial(START) > 0,
        "target-denominator-is-positive": target_denominator > 0,
        "recurrence-is-increasing-on-one-to-two": (
            7 * Fraction(1)**2 - 8 * Fraction(1) + 2 > 0
            and 14 * Fraction(1) - 8 > 0
        ),
        "recurrence-moves-target-upward": target_step > TARGET,
        "all-recorded-iterates-above-target": all(
            bool(item["above_target"]) for item in iterates
        ),
    }
    packet = {
        "status": (
            "recurrence-does-not-reach-target"
            if all(checks.values())
            else "recurrence-gate-failed"
        ),
        "recurrence": "(3*b^2+2*b-2)/(b^2+3*b-2)",
        "fixed_point_polynomial": "b^3-4*b+2",
        "identity": "F(b)-b=-(b^3-4*b+2)/(b^2+3*b-2)",
        "monotonicity_numerator": "7*b^2-8*b+2",
        "induction": (
            "p is increasing on [67/40,2], so its relevant root gamma lies "
            "between 67/40 and 7/4; F is increasing on [1,2] and F(gamma)="
            "gamma, hence beta>gamma implies F(beta)>gamma"
        ),
        "target": "67/40",
        "target_polynomial": (
            f"{target_polynomial.numerator}/{target_polynomial.denominator}"
        ),
        "target_step": f"{target_step.numerator}/{target_step.denominator}",
        "largest_root_decimal": str(largest_root_decimal()),
        "checks": checks,
        "iterates_from_7_over_4": iterates,
        "claim_boundary": (
            "rules out deeper use of this recurrence only; it does not rule "
            "out a different gadget or composition law"
        ),
    }
    print(json.dumps(packet, indent=2, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
