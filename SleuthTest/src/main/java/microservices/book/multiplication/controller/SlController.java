package microservices.book.multiplication.controller;

import org.jboss.logging.Logger;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class SlController {

	public static final Logger logger = Logger.getLogger(SlController.class);
	
	@RequestMapping(value="/sl")
	public ResponseEntity<?> slTest(){
		
		logger.info("In slTestMethod");
		String Message = "from sl";
		return new ResponseEntity<String>(Message, HttpStatus.I_AM_A_TEAPOT);
		
		
	}
}
