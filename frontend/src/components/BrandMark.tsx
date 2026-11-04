/** LAB ERP flask (same shape as favicon.svg, made by desktop/make_logo.py), drawn in the current color. */
export default function BrandMark({ size = 20, logo = "" }: { size?: number; logo?: string }) {
  if (logo) return <img src={logo} width={size} height={size} alt="" style={{ objectFit: "contain", display: "block" }} />;
  return (
    <svg width={size} height={size} viewBox="4 3 24 26" aria-hidden="true">
      <path fill="currentColor" d="M12.5 5L19.5 5Q20.5 5 20.5 6Q20.5 7 19.5 7L19 7L19 12.4L25.2 22.6Q26.6 25.3 23.6 26.5L8.4 26.5Q5.4 25.3 6.8 22.6L13 12.4L13 7L12.5 7Q11.5 7 11.5 6Q11.5 5 12.5 5Z" />
      <path fill="#93c5fd" d="M10.6 18.6L21.4 18.6L23.6 22.3Q24.4 24 22.6 24.4L9.4 24.4Q7.6 24 8.4 22.3Z" />
    </svg>
  );
}
