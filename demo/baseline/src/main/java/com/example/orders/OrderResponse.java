package com.example.orders;

import java.time.Instant;
import java.util.List;

record OrderResponse(Long id, Long customerId, Instant createdAt, List<OrderLineResponse> lines, long totalCents) {

    static OrderResponse from(Order order) {
        var lines = order.getLines().stream()
                .map(OrderLineResponse::from)
                .toList();
        return new OrderResponse(
                order.getId(),
                order.getCustomer().getId(),
                order.getCreatedAt(),
                lines,
                Pricing.orderTotal(order.getLines()));
    }
}
