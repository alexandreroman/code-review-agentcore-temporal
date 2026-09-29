package com.example.orders;

import java.util.Collection;

/**
 * Order pricing rules, in cents.
 */
final class Pricing {

    static final int BULK_QUANTITY = 10;
    static final int BULK_DISCOUNT_PERCENT = 5;

    private Pricing() {
    }

    /**
     * Price of one line: 10 units or more get a 5% discount, rounded down to the cent.
     */
    static long lineTotal(PricedLine line) {
        long gross = line.getQuantity() * line.getUnitPriceCents();
        if (line.getQuantity() >= BULK_QUANTITY) {
            return gross * (100 - BULK_DISCOUNT_PERCENT) / 100;
        }
        return gross;
    }

    static long orderTotal(Collection<? extends PricedLine> lines) {
        return lines.stream()
                .mapToLong(Pricing::lineTotal)
                .sum();
    }
}
