package com.example.orders;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.PositiveOrZero;

record OrderLineRequest(
        @NotBlank String product,
        @NotNull @Positive Integer quantity,
        @NotNull @PositiveOrZero Long unitPriceCents) {
}
