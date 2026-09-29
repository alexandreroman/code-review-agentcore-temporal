package com.example.orders;

import java.util.List;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

/**
 * Fills the in-memory database with a few customers and their orders, so the API is usable right after startup.
 * The n-th customer has n orders, each with n notebooks and 10 * n pens.
 */
@Component
class SampleData implements ApplicationRunner {

    private record SampleCustomer(String name, String email) {
    }

    private static final List<SampleCustomer> CUSTOMERS = List.of(
            new SampleCustomer("Ada Lovelace", "ada@example.com"),
            new SampleCustomer("Grace Hopper", "grace@example.com"),
            new SampleCustomer("Alan Turing", "alan@example.com"));

    private final CustomerRepository customerRepository;
    private final OrderRepository orderRepository;

    SampleData(CustomerRepository customerRepository, OrderRepository orderRepository) {
        this.customerRepository = customerRepository;
        this.orderRepository = orderRepository;
    }

    @Override
    public void run(ApplicationArguments args) {
        for (var index = 0; index < CUSTOMERS.size(); index++) {
            var sample = CUSTOMERS.get(index);
            var customer = customerRepository.save(new Customer(sample.name(), sample.email()));
            var n = index + 1;
            for (var i = 0; i < n; i++) {
                var order = new Order(customer);
                order.addLine(new OrderLine("Notebook", n, 450));
                order.addLine(new OrderLine("Pen", 10 * n, 120));
                orderRepository.save(order);
            }
        }
    }
}
