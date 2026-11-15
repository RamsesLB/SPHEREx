![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white) ![Django](https://img.shields.io/badge/Django-092E20?style=flat&logo=django&logoColor=white) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=white) ![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?style=flat&logo=javascript&logoColor=black) ![Bootstrap](https://img.shields.io/badge/Bootstrap-7952B3?style=flat&logo=bootstrap&logoColor=white) ![Cloudflare](https://img.shields.io/badge/Cloudflare-F38020?style=flat&logo=cloudflare&logoColor=white)

# SPHEREx sky search

Search a sky position in the public IRSA archive, play SPHEREx cutouts, and sum or subtract epochs of the same patch.

Built during the two days of the NASA Space Apps hackathon.

## How it stays up when IRSA does not

A search looks in our own database first. Every observation IRSA has returned is saved there, with the collection and the sky area it covers. If that position was searched before, the list appears at once.

IRSA is asked afterwards, in the background. New rows are stored and the list is updated. If IRSA times out or returns an error, the page keeps the observations already saved instead of going blank.

The same idea applies to the pictures. The first time a cutout, a detector sum, or a subtraction is built, the PNG is stored on Cloudflare R2. The next request for that same image is read back from R2, so the FITS file does not have to be downloaded and rendered again. The disk on the server is only a short-term copy.
