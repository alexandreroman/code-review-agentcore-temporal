package com.example.orders;

import jakarta.validation.Valid;

import org.springframework.http.HttpStatus;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/orders")
class OrderController {

    private final OrderRepository orderRepository;
    private final CustomerRepository customerRepository;

    OrderController(OrderRepository orderRepository, CustomerRepository customerRepository) {
        this.orderRepository = orderRepository;
        this.customerRepository = customerRepository;
    }

    @GetMapping("/{orderId}")
    @Transactional(readOnly = true)
    OrderResponse getOrder(@PathVariable long orderId) {
        var order = orderRepository.findWithCustomerAndLinesById(orderId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "order not found"));
        return OrderResponse.from(order);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    OrderResponse createOrder(@Valid @RequestBody OrderRequest request) {
        var customer = customerRepository.findById(request.customerId())
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "customer not found"));
        var order = new Order(customer);
        for (var line : request.lines()) {
            order.addLine(new OrderLine(line.product(), line.quantity(), line.unitPriceCents()));
        }
        return OrderResponse.from(orderRepository.save(order));
    }
}
