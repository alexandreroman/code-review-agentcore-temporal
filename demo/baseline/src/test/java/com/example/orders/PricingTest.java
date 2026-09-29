package com.example.orders;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.List;

import org.junit.jupiter.api.Test;

class PricingTest {

    private record Line(int quantity, long unitPriceCents) implements PricedLine {

        @Override
        public int getQuantity() {
            return quantity;
        }

        @Override
        public long getUnitPriceCents() {
            return unitPriceCents;
        }
    }

    @Test
    void lineBelowBulkQuantityPaysFullPrice() {
        assertEquals(900, Pricing.lineTotal(new Line(9, 100)));
    }

    @Test
    void bulkLineGetsFivePercentOffRoundedDown() {
        assertEquals(950, Pricing.lineTotal(new Line(10, 100)));
        assertEquals(3163, Pricing.lineTotal(new Line(10, 333)));
    }

    @Test
    void orderTotalSumsItsLines() {
        assertEquals(450 + 1140, Pricing.orderTotal(List.of(new Line(1, 450), new Line(10, 120))));
        assertEquals(0, Pricing.orderTotal(List.of()));
    }
}
