package com.example.orders;

record OrderLineResponse(String product, int quantity, long unitPriceCents) {

    static OrderLineResponse from(OrderLine line) {
        return new OrderLineResponse(line.getProduct(), line.getQuantity(), line.getUnitPriceCents());
    }
}
