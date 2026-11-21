public class Features {
    static boolean isPrime(int n) {
        if (n < 2) return false;
        for (int d = 2; d * d <= n; d++) {
            if (n % d == 0) return false;
        }
        return true;
    }

    static int gcd(int a, int b) {
        while (b != 0) {
            int t = a % b;
            a = b;
            b = t;
        }
        return a;
    }

    static void greet(String name) {
        System.out.println("Hello, " + name + "!");
    }

    public static void main(String[] args) {
        greet("compiler");
        String primes = "";
        for (int n = 0; n < 30; n++) {
            if (isPrime(n)) primes = primes + n + " ";
        }
        System.out.println("primes: " + primes);
        System.out.println("gcd(84, 36) = " + gcd(84, 36));
        System.out.println("-7 / 2 = " + (-7 / 2) + ", -7 % 2 = " + (-7 % 2));
        System.out.println("overflow: " + (2147483647 + 1));
        int x = 5;
        int y = x++ + ++x;
        System.out.println("x = " + x + ", y = " + y);
        boolean ok = x > 3 && !(y == 0) || false;
        System.out.println("ok = " + ok);
        System.out.print("no newline, ");
        System.out.println();
    }
}
