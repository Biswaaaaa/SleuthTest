package microservices.book.multiplication.config;

import org.springframework.cloud.sleuth.sampler.ProbabilityBasedSampler;
import org.springframework.context.annotation.Configuration;

@Configuration
public class CloudConfig {

	
	public ProbabilityBasedSampler defaultSampler() {
		return new ProbabilityBasedSampler();
	}
}
